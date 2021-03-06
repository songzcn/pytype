"""Tests for matching against protocols.

Based on PEP 544 https://www.python.org/dev/peps/pep-0544/.
"""


from pytype import utils
from pytype.tests import test_base


class ProtocolTest(test_base.BaseTest):
  """Tests for protocol implementation."""

  def test_check_protocol(self):
    self.Check("""
      from __future__ import google_type_annotations
      import protocols
      from typing import Sized
      def f(x: protocols.Sized):
        return None
      def g(x: Sized):
        return None
      class Foo:
        def __len__(self):
          return 5
      f([])
      foo = Foo()
      f(foo)
      g([])
      g(foo)
    """)

  def test_check_iterator(self):
    self.Check("""
      from __future__ import google_type_annotations
      from typing import Iterator
      def f(x: Iterator):
        return None
      class Foo:
        def next(self):
          return None
        def __iter__(self):
          return None
      foo = Foo()
      f(foo)
    """)

  def test_check_parameterized_iterator(self):
    self.Check("""
      from __future__ import google_type_annotations
      from typing import Iterator
      def f(x: Iterator[int]):
        return None
      class Foo:
        def next(self):
          return 42
        def __iter__(self):
          return self
      f(Foo())
    """)

  def test_check_protocol_error(self):
    _, errors = self.InferWithErrors("""\
      from __future__ import google_type_annotations
      import protocols

      def f(x: protocols.SupportsAbs):
        return x.__abs__()
      f(["foo"])
    """)
    self.assertErrorLogIs(errors, [(6, "wrong-arg-types",
                                    r"\(x: SupportsAbs\).*\(x: List\[str\]\)")])

  def test_check_iterator_error(self):
    _, errors = self.InferWithErrors("""\
      from __future__ import google_type_annotations
      from typing import Iterator
      def f(x: Iterator[int]):
        return None
      class Foo:
        def next(self) -> str:
          return ''
        def __iter__(self):
          return self
      f(Foo())  # line 10
    """)
    self.assertErrorLogIs(
        errors, [(10, "wrong-arg-types", r"Iterator\[int\].*Foo")])

  def test_check_protocol_match_unknown(self):
    self.Check("""\
      from __future__ import google_type_annotations
      from typing import Sized
      def f(x: Sized):
        pass
      class Foo(object):
        pass
      def g(x):
        foo = Foo()
        foo.__class__ = x
        f(foo)
    """)

  def test_check_protocol_against_garbage(self):
    _, errors = self.InferWithErrors("""\
      from __future__ import google_type_annotations
      from typing import Sized
      def f(x: Sized):
        pass
      class Foo(object):
        pass
      def g(x):
        foo = Foo()
        foo.__class__ = 42
        f(foo)
    """)
    self.assertErrorLogIs(errors, [(10, "wrong-arg-types", r"\(x: Sized\)")])

  def test_check_parameterized_protocol(self):
    self.Check("""\
      from __future__ import google_type_annotations
      from typing import Iterator, Iterable

      class Foo(object):
        def __iter__(self) -> Iterator[int]:
          return iter([])

      def f(x: Iterable[int]):
        pass

      foo = Foo()
      f(foo)
      f(iter([3]))
    """)

  def test_check_parameterized_protocol_error(self):
    _, errors = self.InferWithErrors("""\
      from __future__ import google_type_annotations
      from typing import Iterator, Iterable

      class Foo(object):
        def __iter__(self) -> Iterator[str]:
          return iter([])

      def f(x: Iterable[int]):
        pass

      foo = Foo()
      f(foo)
    """)
    self.assertErrorLogIs(errors, [(12, "wrong-arg-types",
                                    r"\(x: Iterable\[int\]\).*\(x: Foo\)")])

  def test_check_parameterized_protocol_multi_signature(self):
    self.Check("""\
      from __future__ import google_type_annotations
      from typing import Sequence, Union

      class Foo(object):
        def __len__(self):
          return 0
        def __getitem__(self, x: Union[int, slice]) -> Union[int, Sequence[int]]:
          return 0

      def f(x: Sequence[int]):
        pass

      foo = Foo()
      f(foo)
    """)

  def test_check_parameterized_protocol_error_multi_signature(self):
    _, errors = self.InferWithErrors("""\
      from __future__ import google_type_annotations
      from typing import Sequence, Union

      class Foo(object):
        def __len__(self):
          return 0
        def __getitem__(self, x: int) -> int:
          return 0

      def f(x: Sequence[int]):
        pass

      foo = Foo()
      f(foo)
    """)
    self.assertErrorLogIs(errors, [(14, "wrong-arg-types",
                                    r"\(x: Sequence\[int\]\).*\(x: Foo\)")])

  def test_use_iterable(self):
    ty = self.Infer("""
      class A(object):
        def __iter__(self):
          return iter(__any_object__)
      v = list(A())
    """, deep=False)
    self.assertTypesMatchPytd(ty, """
      from typing import Any
      class A(object):
        def __iter__(self) -> Any: ...
      v = ...  # type: list
    """)

  def test_construct_dict_with_protocol(self):
    self.Check("""
      from __future__ import google_type_annotations
      class Foo(object):
        def __iter__(self):
          pass
      def f(x: Foo):
        return dict(x)
    """)

  def test_method_on_superclass(self):
    self.Check("""
      from __future__ import google_type_annotations
      class Foo(object):
        def __iter__(self):
          pass
      class Bar(Foo):
        pass
      def f(x: Bar):
        return iter(x)
    """)

  def test_method_on_parameterized_superclass(self):
    self.Check("""
      from __future__ import google_type_annotations
      from typing import List
      class Bar(List[int]):
        pass
      def f(x: Bar):
        return iter(x)
    """)

  def test_any_superclass(self):
    self.Check("""
      from __future__ import google_type_annotations
      class Bar(__any_object__):
        pass
      def f(x: Bar):
        return iter(x)
    """)

  def test_multiple_options(self):
    self.Check("""
      from __future__ import google_type_annotations
      class Bar(object):
        if __random__:
          def __iter__(self): return 1
        else:
          def __iter__(self): return 2
      def f(x: Bar):
        return iter(x)
    """)

  def test_iterable(self):
    ty = self.Infer("""
      from __future__ import google_type_annotations
      from typing import Iterable, Iterator, TypeVar
      T = TypeVar("T")
      class Bar(object):
        def __getitem__(self, i: T) -> T:
          if i > 10:
            raise IndexError()
          return i
      T2 = TypeVar("T2")
      def f(s: Iterable[T2]) -> Iterator[T2]:
        return iter(s)
      next(f(Bar()))
    """, deep=False)
    self.assertTypesMatchPytd(ty, """
      from typing import Iterable, Iterator, TypeVar
      T = TypeVar("T")
      class Bar(object):
        def __getitem__(self, i: T) -> T: ...
      T2 = TypeVar("T2")
      def f(s: Iterable[T2]) -> Iterator[T2]
    """)

  def test_pyi_iterable(self):
    with utils.Tempdir() as d:
      d.create_file("foo.pyi", """
        T = TypeVar("T")
        class Foo(object):
          def __getitem__(self, i: T) -> T: ...
      """)
      self.Check("""
        from __future__ import google_type_annotations
        from typing import Iterable, TypeVar
        import foo
        T = TypeVar("T")
        def f(s: Iterable[T]) -> T: ...
        f(foo.Foo())
      """, pythonpath=[d.path])

  def test_inherited_abstract_method(self):
    self.Check("""
      from __future__ import google_type_annotations
      from typing import Iterator
      class Foo(object):
        def __iter__(self) -> Iterator[int]:
          return __any_object__
        def next(self):
          return __any_object__
      def f(x: Iterator[int]):
        pass
      f(Foo())
    """)

  def test_inherited_abstract_method_error(self):
    _, errors = self.InferWithErrors("""\
      from __future__ import google_type_annotations
      from typing import Iterator
      class Foo(object):
        def __iter__(self) -> Iterator[str]:
          return __any_object__
        def next(self):
          return __any_object__
      def f(x: Iterator[int]):
        pass
      f(Foo())  # line 10
    """)
    self.assertErrorLogIs(
        errors, [(10, "wrong-arg-types", r"Iterator\[int\].*Foo")])

  def test_reversible(self):
    self.Check("""
      from __future__ import google_type_annotations
      from typing import Reversible
      class Foo(object):
        def __reversed__(self):
          pass
      def f(x: Reversible):
        pass
      f(Foo())
    """)

  def test_collection(self):
    self.Check("""
      from __future__ import google_type_annotations
      from typing import Collection
      class Foo(object):
        def __contains__(self, x):
          pass
        def __iter__(self):
          pass
        def __len__(self):
          pass
      def f(x: Collection):
        pass
      f(Foo())
    """)

  def test_hashable(self):
    self.Check("""
      from __future__ import google_type_annotations
      from typing import Hashable
      class Foo(object):
        def __hash__(self):
          pass
      def f(x: Hashable):
        pass
      f(Foo())
    """)

  def test_list_hash(self):
    errors = self.CheckWithErrors("""\
      from __future__ import google_type_annotations
      from typing import Hashable
      def f(x: Hashable):
        pass
      f([])  # line 5
    """)
    self.assertErrorLogIs(
        errors, [(5, "wrong-arg-types", r"Hashable.*List.*__hash__")])

  def test_hash_constant(self):
    errors = self.CheckWithErrors("""\
      from __future__ import google_type_annotations
      from typing import Hashable
      class Foo(object):
        __hash__ = None
      def f(x: Hashable):
        pass
      f(Foo())  # line 7
    """)
    self.assertErrorLogIs(
        errors, [(7, "wrong-arg-types", r"Hashable.*Foo.*__hash__")])


if __name__ == "__main__":
  test_base.main()
