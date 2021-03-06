"""Test cases that match the examples in our documentation."""

from pytype import utils
from pytype.tests import test_base


class WorkflowTest(test_base.BaseTest):
  """Tests for examples extracted from our documentation."""

  def testTutorial1(self):
    _, errors = self.InferWithErrors("""\
      from __future__ import google_type_annotations
      def f(x: int, y: int) -> int:
        return "foo"
      """, deep=True)
    self.assertErrorLogIs(errors, [
        (3, "bad-return-type")
    ])

  def testTutorial2(self):
    self.Check("""\
      from __future__ import google_type_annotations
      from typing import Any, Dict, List
      def keys(d: Dict[str, Any]) -> List[str]:
        return list(d.keys())

      keys({"foo": 3})
      """)

  def testTutorial3(self):
    self.Check("""\
      from __future__ import google_type_annotations
      from typing import Optional

      def find_name_in_list(d: list, name: str) -> Optional[int]:
        try:
          return d.index(name)
        except ValueError:
          return None

      find_name_in_list(["foo", "bar"], "foo")
    """)

  def testTutorial4(self):
    _, errors = self.InferWithErrors("""\
      import socket
      class Server:
        def __init__(self, port):
         self.port = port

        def listen(self):
          self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
          self.socket.bind((socket.gethostname(), self.port))
          self.socket.listen(backlog=5)

        def accept(self):
          return self.socket.accept()
    """)
    self.assertErrorLogIs(errors, [
        (12, "attribute-error")
    ])

  def testTutorial5(self):
    self.Check("""\
      import socket
      class Server:
        def __init__(self, port):
         self.port = port

        def listen(self):
          self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
          self.socket.bind((socket.gethostname(), self.port))
          self.socket.listen(backlog=5)

        def accept(self):
          return self.socket.accept()  # pytype: disable=attribute-error
    """)

  def testTutorial6(self):
    with utils.Tempdir() as d:
      d.create_file("ftp.pyi", """
        class Server:
          def start(self): ...
      """)
      self.Check("""\
        from __future__ import google_type_annotations
        import ftp

        def start_ftp_server(server: ftp.Server):
          return server.start()
      """, pythonpath=[d.path])

  def testTutorial7(self):
    with utils.Tempdir() as d:
      d.create_file("ftp.pyi", """
        class Server:
          def start(self): ...
      """)
      self.Check("""\
        from __future__ import google_type_annotations
        import typing

        if typing.TYPE_CHECKING:
          import ftp

        def start_ftp_server(server: ftp.Server):
            return server.start()
      """, pythonpath=[d.path])


if __name__ == "__main__":
  test_base.main()
