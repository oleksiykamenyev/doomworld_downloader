# Stubbed out stuff mostly
# TODO: Move this to a separate repo/package
from abc import ABC


class Demo(ABC):
    def parse_header(self):
        pass

    def parse_movements(self):
        pass


class LMPParser:
    def __init__(self):
        pass

    def parse_demo(self, demo_path):
        with open(demo_path, "rb") as demo_stream:
            demo_bytes = demo_stream.read()

        # Call _get_parser

        # Call parser.parse

    def _get_parser(self, demo_bytes):
        # Returns parser for detected type of demo
        pass


def main():
    # TODO: Add argument parsing
    args = {'demos': []}

    # TODO: Parse every demo
    demo = args['demos'][0]
    with open(demo, "rb") as demo_stream:
        demo_bytes = demo_stream.read()




if __name__ == '__main__':
    main()
