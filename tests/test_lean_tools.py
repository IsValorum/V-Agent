"""The tool block sent to the model loses only what says nothing; every instruction and constraint stays."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))

from mcp_prompt import lean_tools

TOOL = {'type': 'function', 'function': {'name': 'pc__fs_read', 'description': 'Read a UTF-8 text file.', 'parameters': {
    'type': 'object', 'title': 'fs_readArguments', 'required': [],
    'properties': {
        'path': {'type': 'string', 'title': 'Path', 'description': 'Relative to the working folder (e.g. notes.txt), or an '
                 'absolute PC path when Full-PC access is enabled. Must be a file; use fs_list for directories.'},
        'find': {'type': ['string', 'null'], 'default': None, 'title': 'Find'},
        'headers': {'anyOf': [{'type': 'object', 'additionalProperties': True}, {'type': 'null'}]},
        'body': {'anyOf': [{'type': 'string'}, {'type': 'array', 'items': {}}, {'type': 'null'}]},
        'lines': {'type': 'integer', 'minimum': 1, 'maximum': 240, 'default': 100, 'description': 'Number of lines; default 100.'},
        'mode': {'type': 'string', 'enum': ['a', 'b']},
    }}}}


class LeanToolsTests(unittest.TestCase):
    def test_keeps_instructions_and_constraints(self):
        fn = lean_tools([TOOL])[0]['function']
        props = fn['parameters']['properties']
        self.assertEqual(fn['description'], 'Read a UTF-8 text file.')
        self.assertEqual(props['path'], {'type': 'string', 'description': 'Must be a file; use fs_list for directories.'})
        self.assertEqual(props['lines'], TOOL['function']['parameters']['properties']['lines'])
        self.assertEqual(props['mode']['enum'], ['a', 'b'])

    def test_drops_only_what_says_nothing(self):
        params = lean_tools([TOOL])[0]['function']['parameters']
        self.assertNotIn('title', params)
        self.assertNotIn('required', params)
        self.assertEqual(params['properties']['find'], {'type': 'string'})
        self.assertEqual(params['properties']['headers'], {'type': 'object'})
        self.assertEqual(params['properties']['body'], {'anyOf': [{'type': 'string'}, {'type': 'array'}]})
        self.assertIn('Relative to the working folder', str(TOOL))     # the original is never changed

    def test_values_are_never_edited(self):
        tool = {'type': 'function', 'function': {'name': 'x', 'parameters': {'type': 'object', 'properties': {
            'opts': {'type': 'object', 'default': {'title': 'kept', 'required': []}},
            'kind': {'type': 'object', 'enum': [{'title': 'a'}]}}}}}
        props = lean_tools([tool])[0]['function']['parameters']['properties']
        self.assertEqual(props['opts']['default'], {'title': 'kept', 'required': []})
        self.assertEqual(props['kind']['enum'], [{'title': 'a'}])

    def test_a_null_optional_argument_is_still_accepted(self):
        from mcp_prompt import validate_tool_arguments
        params = lean_tools([TOOL])[0]['function']['parameters']
        args = {'path': 'a.txt', 'find': None}
        validate_tool_arguments(params, args)                 # no "expected string"
        self.assertEqual(args, {'path': 'a.txt'})             # left out: the tool's default applies


if __name__ == '__main__':
    unittest.main()
