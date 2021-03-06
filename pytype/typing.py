"""Implementation of the types in Python 3's typing.py."""

# pylint's detection of this is error-prone:
# pylint: disable=unpacking-non-sequence


from pytype import abstract
from pytype import collections_overlay
from pytype import function
from pytype import overlay
from pytype.pytd import pep484
from pytype.pytd import pytd
from pytype.pytd import visitors


class TypingOverlay(overlay.Overlay):
  """A representation of the 'typing' module that allows custom overlays."""

  def __init__(self, vm):
    # Make sure we have typing available as a dependency
    if not vm.loader.can_see("typing"):
      vm.errorlog.missing_typing_dependency()
    member_map = typing_overload.copy()
    ast = vm.loader.typing
    for cls in ast.classes:
      _, name = cls.name.rsplit(".", 1)
      if name not in member_map and pytd.IsContainer(cls) and cls.template:
        member_map[name] = TypingContainer
    super(TypingOverlay, self).__init__(vm, "typing", member_map, ast)


class Union(abstract.AnnotationClass):
  """Implementation of typing.Union[...]."""

  def __init__(self, name, vm, options=()):
    super(Union, self).__init__(name, vm)
    self.options = options

  def _build_value(self, node, inner, _):
    return abstract.Union(self.options + inner, self.vm)


class TypingContainer(abstract.AnnotationContainer):

  def __init__(self, name, vm):
    if name in pep484.PEP484_CAPITALIZED:
      pytd_name = "__builtin__." + name.lower()
    else:
      pytd_name = "typing." + name
    base = vm.convert.name_to_value(pytd_name)
    super(TypingContainer, self).__init__(name, vm, base)


class Tuple(TypingContainer):

  def _get_value_info(self, inner, ends_with_ellipsis):
    if not ends_with_ellipsis:
      template = range(len(inner)) + [abstract.T]
      inner += (abstract.merge_values(inner, self.vm),)
      return template, inner, abstract.TupleClass
    else:
      return super(Tuple, self)._get_value_info(inner, ends_with_ellipsis)


class Callable(TypingContainer):
  """Implementation of typing.Callable[...]."""

  def getitem_slot(self, node, slice_var):
    content = self._maybe_extract_tuple(node, slice_var)
    inner, ends_with_ellipsis = self._build_inner(content)
    args = inner[0]
    if isinstance(args, abstract.List) and not args.could_contain_anything:
      inner[0], _ = self._build_inner(args.pyval)
    else:
      if args.cls and any(v.full_name == "__builtin__.list"
                          for v in args.cls.data):
        self.vm.errorlog.invalid_annotation(
            self.vm.frames, args, "Must be constant")
      elif (args is not self.vm.convert.ellipsis and
            not isinstance(args, abstract.Unsolvable)):
        self.vm.errorlog.invalid_annotation(
            self.vm.frames, args,
            "First argument to Callable must be a list of argument types.")
      inner[0] = self.vm.convert.unsolvable
    value = self._build_value(node, tuple(inner), ends_with_ellipsis)
    return node, value.to_variable(node)

  def _get_value_info(self, inner, ends_with_ellipsis):
    if isinstance(inner[0], list):
      template = range(len(inner[0])) + [t.name for t in self.base_cls.template]
      combined_args = abstract.merge_values(inner[0], self.vm)
      inner = tuple(inner[0]) + (combined_args,) + inner[1:]
      return template, inner, abstract.Callable
    else:
      return super(Callable, self)._get_value_info(inner, ends_with_ellipsis)


class TypeVarError(Exception):
  """Raised if an error is encountered while initializing a TypeVar."""

  def __init__(self, message, bad_call=None):
    super(TypeVarError, self).__init__(message)
    self.bad_call = bad_call


class TypeVar(abstract.PyTDFunction):
  """Representation of typing.TypeVar, as a function."""

  def __init__(self, name, vm):
    pyval = vm.loader.typing.Lookup("typing._typevar_new")
    f = vm.convert.constant_to_value(pyval, {}, vm.root_cfg_node)
    super(TypeVar, self).__init__(name, f.signatures, pytd.METHOD, vm)

  def _get_class_or_constant(self, var, name, arg_type):
    if arg_type is abstract.Class:
      convert_func = abstract.get_atomic_value
      type_desc = "an unambiguous type"
    else:
      convert_func = abstract.get_atomic_python_constant
      type_desc = "a constant " + arg_type.__name__
    try:
      return convert_func(var, arg_type)
    except abstract.ConversionError:
      raise TypeVarError("%s must be %s" % (name, type_desc))

  def _get_namedarg(self, args, name, arg_type, default_value):
    if name in args.namedargs:
      value = self._get_class_or_constant(args.namedargs[name], name, arg_type)
      if name != "bound":
        self.vm.errorlog.not_supported_yet(
            self.vm.frames, "argument \"%s\" to TypeVar" % name)
      return value
    return default_value

  def _get_typeparam(self, node, args):
    args = args.simplify(node)
    try:
      self._match_args(node, args)
    except abstract.InvalidParameters as e:
      raise TypeVarError("wrong arguments", e.bad_call)
    except abstract.FailedFunctionCall:
      # It is currently impossible to get here, since the only
      # FailedFunctionCall that is not an InvalidParameters is NotCallable.
      raise TypeVarError("initialization failed")
    name = self._get_class_or_constant(args.posargs[0], "name", str)
    constraints = tuple(self._get_class_or_constant(
        c, "constraint", abstract.Class) for c in args.posargs[1:])
    if len(constraints) == 1:
      raise TypeVarError("the number of constraints must be 0 or more than 1")
    bound = self._get_namedarg(args, "bound", abstract.Class, None)
    covariant = self._get_namedarg(args, "covariant", bool, False)
    contravariant = self._get_namedarg(args, "contravariant", bool, False)
    if constraints and bound:
      raise TypeVarError("constraints and a bound are mutually exclusive")
    extra_kwargs = set(args.namedargs) - {"bound", "covariant", "contravariant"}
    if extra_kwargs:
      raise TypeVarError("extra keyword arguments: " + ", ".join(extra_kwargs))
    if args.starargs:
      raise TypeVarError("*args must be a constant tuple")
    if args.starstarargs:
      raise TypeVarError("ambiguous **kwargs not allowed")
    return abstract.TypeParameter(name, self.vm, constraints=constraints,
                                  bound=bound, covariant=covariant,
                                  contravariant=contravariant)

  def call(self, node, _, args):
    """Call typing.TypeVar()."""
    try:
      param = self._get_typeparam(node, args)
    except TypeVarError as e:
      self.vm.errorlog.invalid_typevar(self.vm.frames, e.message, e.bad_call)
      return node, self.vm.convert.unsolvable.to_variable(node)
    return node, param.to_variable(node)


class Cast(abstract.PyTDFunction):
  """Implements typing.cast."""

  def call(self, node, func, args):
    if args.posargs:
      try:
        annot = self.vm.annotations_util.process_annotation_var(
            args.posargs[0], "typing.cast", self.vm.frames, node)
      except self.vm.annotations_util.LateAnnotationError:
        self.vm.errorlog.invalid_annotation(
            self.vm.frames,
            abstract.merge_values(args.posargs[0].data, self.vm),
            "Forward references not allowed in typing.cast.\n"
            "Consider switching to a type comment.")
        annot = self.vm.convert.create_new_unsolvable(node)
      args = args.replace(posargs=(annot,) + args.posargs[1:])
    return super(Cast, self).call(node, func, args)


class NoReturn(abstract.AtomicAbstractValue):

  def __init__(self, vm):
    super(NoReturn, self).__init__("NoReturn", vm)

  def get_class(self):
    return self.to_variable(self.vm.root_cfg_node)


def build_any(name, vm):
  del name
  return abstract.Unsolvable(vm)


class NamedTupleBuilder(collections_overlay.NamedTupleBuilder):
  """Factory for creating typing.NamedTuple classes."""

  def __init__(self, name, vm):
    self.typing_ast = vm.loader.import_name("typing")
    # Because NamedTuple is a special case for the pyi parser, typing.pytd has
    # "_NamedTuple" instead. Replace the name of the returned function so that
    # error messages will correctly display "typing.NamedTuple".
    pyval = self.typing_ast.Lookup("typing._NamedTuple")
    pyval = pyval.Replace(name="typing.NamedTuple")
    super(NamedTupleBuilder, self).__init__(name, vm, pyval)

  def _getargs(self, node, args):
    self._match_args(node, args)
    # Normally we would use typing.NamedTuple.__new__ to match args to
    # parameters, but we can't import typing.
    # TODO(tsudol): Replace with typing.NamedTuple.__new__.
    f = function.Signature.from_param_names("typing.NamedTuple",
                                            ["typename", "fields"])
    callargs = {arg_name: arg_var for arg_name, arg_var, _ in f.iter_args(args)}
    # typing.NamedTuple doesn't support rename or verbose
    name_var = callargs["typename"]
    fields_var = callargs["fields"]
    fields = abstract.get_atomic_python_constant(fields_var)
    # The fields is a list of tuples, so we need to deeply unwrap them.
    fields = [abstract.get_atomic_python_constant(t) for t in fields]
    # We need the actual string for the field names and the AtomicAbstractValue
    # for the field types.
    names = []
    types = []
    for (name, typ) in fields:
      names.append(abstract.get_atomic_python_constant(name))
      types.append(abstract.get_atomic_value(typ))
    return name_var, names, types

  def _build_namedtuple(self, name, field_names, field_types, node):
    # Build an InterpreterClass representing the namedtuple.
    if field_types:
      field_types_union = abstract.Union(field_types, self.vm)
    else:
      field_types_union = self.vm.convert.none_type
    members = {n: t.instantiate(node) for n, t in zip(field_names, field_types)}
    # collections.namedtuple has: __dict__, __slots__ and _fields.
    # typing.NamedTuple adds: _field_types, __annotations__ and _field_defaults.
    # __slots__ and _fields are tuples containing the names of the fields.
    slots = tuple(self.vm.convert.build_string(node, f) for f in field_names)
    members["__slots__"] = abstract.Tuple(slots, self.vm).to_variable(node)
    members["_fields"] = abstract.Tuple(slots, self.vm).to_variable(node)
    # __dict__ and _field_defaults are both collections.OrderedDicts that map
    # field names (strings) to objects of the field types.
    ordered_dict_cls = self.vm.convert.name_to_value("collections.OrderedDict",
                                                     ast=self.collections_ast)
    # Normally, we would use abstract.K and abstract.V, but collections.pyi
    # doesn't conform to that standard.
    field_dict_cls = abstract.ParameterizedClass(
        ordered_dict_cls,
        {"K": self.vm.convert.str_type, "V": field_types_union},
        self.vm)
    members["__dict__"] = field_dict_cls.instantiate(node)
    members["_field_defaults"] = field_dict_cls.instantiate(node)
    # _field_types and __annotations__ are both collections.OrderedDicts
    # that map field names (strings) to the types of the fields.
    # The `type` must be parameterized with `object` in order to produce
    # `collections.OrderedDict[str, type]`.
    # Otherwise, it will produce `collections.OrderedDict[str, Any]`.
    type_type = abstract.ParameterizedClass(
        self.vm.convert.type_type,
        {abstract.T: self.vm.convert.object_type},
        self.vm)
    field_types_cls = abstract.ParameterizedClass(
        ordered_dict_cls,
        {"K": self.vm.convert.str_type, "V": type_type},
        self.vm)
    members["_field_types"] = field_types_cls.instantiate(node)
    members["__annotations__"] = field_types_cls.instantiate(node)
    # __new__
    new_annots = {}
    new_lates = {}
    for (n, t) in zip(field_names, field_types):
      # We don't support late annotations yet, but once we do, they'll show up
      # as LateAnnotation objects to be stored in new_lates.
      new_annots[n] = t
    # We set the bound on this TypeParameter later. This gives __new__ the
    # signature: def __new__(cls: Type[_Tname], ...) -> _Tname, i.e. the same
    # signature that visitor.CreateTypeParametersForSignatures would create.
    # This allows subclasses of the NamedTuple to get the correct type from
    # their constructors.
    cls_type_param = abstract.TypeParameter(
        visitors.CreateTypeParametersForSignatures.PREFIX + name,
        self.vm, bound=None)
    new_annots["cls"] = abstract.ParameterizedClass(
        self.vm.convert.type_type, {abstract.T: cls_type_param}, self.vm)
    new_annots["return"] = cls_type_param
    members["__new__"] = abstract.SimpleFunction(
        name="__new__",
        param_names=("cls",) + tuple(field_names),
        varargs_name=None,
        kwonly_params=(),
        kwargs_name=None,
        defaults={},
        annotations=new_annots,
        late_annotations=new_lates,
        vm=self.vm).to_variable(node)
    # __init__
    members["__init__"] = abstract.SimpleFunction(
        name="__init__",
        param_names=("self",),
        varargs_name="args",
        kwonly_params=(),
        kwargs_name="kwargs",
        defaults={},
        annotations={},
        late_annotations={},
        vm=self.vm).to_variable(node)
    # _make
    # _make is a classmethod, so it needs to be wrapped by
    # specialibuiltins.ClassMethodInstance.
    # Like __new__, it uses the _Tname TypeVar.
    sized_cls = self.vm.convert.name_to_value("typing.Sized")
    iterable_type = abstract.ParameterizedClass(
        self.vm.convert.name_to_value("typing.Iterable"),
        {abstract.T: field_types_union}, self.vm)
    make = abstract.SimpleFunction(
        name="_make",
        param_names=("cls", "iterable", "new", "len"),
        varargs_name=None,
        kwonly_params=(),
        kwargs_name=None,
        defaults={
            "new": self.vm.convert.unsolvable.to_variable(node),
            "len": self.vm.convert.unsolvable.to_variable(node)
        },
        annotations={
            "cls": abstract.ParameterizedClass(
                self.vm.convert.type_type,
                {abstract.T: cls_type_param}, self.vm),
            "iterable": iterable_type,
            "new": self.vm.convert.unsolvable,
            "len": abstract.Callable(
                self.vm.convert.name_to_value("typing.Callable"),
                {0: sized_cls,
                 abstract.ARGS: sized_cls,
                 abstract.RET: self.vm.convert.int_type},
                self.vm),
            "return": cls_type_param
        },
        late_annotations={},
        vm=self.vm).to_variable(node)
    make_args = abstract.FunctionArgs(posargs=(make,))
    _, members["_make"] = self.vm.special_builtins["classmethod"].call(
        node, None, make_args)
    # _replace
    # Like __new__, it uses the _Tname TypeVar. We have to annotate the `self`
    # param to make sure the TypeVar is substituted correctly.
    members["_replace"] = abstract.SimpleFunction(
        name="_replace",
        param_names=("self",),
        varargs_name=None,
        kwonly_params=(),
        kwargs_name="kwds",
        defaults={},
        annotations={
            "self": cls_type_param,
            "kwds": field_types_union,
            "return": cls_type_param
        },
        late_annotations={},
        vm=self.vm).to_variable(node)
    # __getnewargs__
    getnewargs_tuple_params = dict(
        tuple(enumerate(field_types)) + ((abstract.T, field_types_union),))
    getnewargs_tuple = abstract.TupleClass(self.vm.convert.tuple_type,
                                           getnewargs_tuple_params, self.vm)
    members["__getnewargs__"] = abstract.SimpleFunction(
        name="__getnewargs__",
        param_names=("self",),
        varargs_name=None,
        kwonly_params=(),
        kwargs_name=None,
        defaults={},
        annotations={"return": getnewargs_tuple},
        late_annotations={},
        vm=self.vm).to_variable(node)
    # __getstate__
    members["__getstate__"] = abstract.SimpleFunction(
        name="__getstate__",
        param_names=("self",),
        varargs_name=None,
        kwonly_params=(),
        kwargs_name=None,
        defaults={},
        annotations={},
        late_annotations={},
        vm=self.vm).to_variable(node)
    # _asdict
    members["_asdict"] = abstract.SimpleFunction(
        name="_asdict",
        param_names=("self",),
        varargs_name=None,
        kwonly_params=(),
        kwargs_name=None,
        defaults={},
        annotations={"return": field_dict_cls},
        late_annotations={},
        vm=self.vm).to_variable(node)
    # Finally, make the class.
    abs_membs = abstract.Dict(self.vm)
    abs_membs.update(node, members)
    cls_var = self.vm.make_class(
        node=node,
        name_var=self.vm.convert.build_string(node, name),
        bases=[self.vm.convert.tuple_type.to_variable(node)],
        class_dict_var=abs_membs.to_variable(node),
        cls_var=None)
    # Now that the class has been made, we can complete the TypeParameter used
    # by __new__, _make and _replace.
    cls_type_param.bound = cls_var.data[0]
    return cls_var

  def call(self, node, _, args):
    try:
      name_var, field_names, field_types = self._getargs(node, args)
    except abstract.ConversionError:
      return node, self.vm.convert.unsolvable.to_variable(node)

    try:
      name = abstract.get_atomic_python_constant(name_var)
    except abstract.ConversionError:
      return node, self.vm.convert.unsolvable.to_variable(node)

    try:
      field_names = self._validate_and_rename_args(name, field_names, False)
    except ValueError as e:
      self.vm.errorlog.invalid_namedtuple_arg(self.vm.frames, e.message)
      return node, self.vm.convert.unsolvable.to_variable(node)

    annots, late_annots = self.vm.annotations_util.convert_annotations_list(
        zip(field_names, field_types))
    if late_annots:
      # We currently don't support forward references. Report if we find any,
      # then continue by using Unsolvable instead.
      self.vm.errorlog.not_supported_yet(
          self.vm.frames, "Forward references in typing.NamedTuple")
    field_types = [annots.get(field_name, self.vm.convert.unsolvable)
                   for field_name in field_names]

    cls_var = self._build_namedtuple(name, field_names, field_types, node)
    self.vm.trace_classdef(cls_var)
    return node, cls_var


def build_optional(name, vm):
  return Union(name, vm, (vm.convert.none_type,))


def build_generic(name, vm):
  vm.errorlog.not_supported_yet(vm.frames, "typing." + name)
  return vm.convert.unsolvable


def build_typechecking(name, vm):
  del name
  return vm.convert.true


def build_cast(name, vm):
  f = vm.lookup_builtin("typing.cast")
  signatures = [abstract.PyTDSignature(name, sig, vm) for sig in f.signatures]
  return Cast(name, signatures, f.kind, vm)


def build_newtype(name, vm):
  vm.errorlog.not_supported_yet(vm.frames, "typing." + name)
  return vm.convert.unsolvable


def build_noreturn(name, vm):
  del name
  return vm.convert.no_return


typing_overload = {
    "Any": build_any,
    "Callable": Callable,
    "Generic": build_generic,
    "NamedTuple": NamedTupleBuilder,
    "NewType": build_newtype,
    "NoReturn": build_noreturn,
    "Optional": build_optional,
    "Tuple": Tuple,
    "TypeVar": TypeVar,
    "Union": Union,
    "TYPE_CHECKING": build_typechecking,
    "cast": build_cast,
}
