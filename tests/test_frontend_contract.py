"""Verify the independently enforced Python/JavaScript diagnostic boundary."""

import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from afk_grinder.capture import (CAPTURE_DIAGNOSTIC_CODES, CAPTURE_DIAGNOSTIC_ERROR_TYPES,
                                 CAPTURE_DIAGNOSTIC_STAGES)

SOURCE = (Path(__file__).resolve().parents[1] / 'src/afk_grinder/web/app.js').read_text()


class FrontendContractTests(unittest.TestCase):
    def test_diagnostic_vocabularies_match_backend_contract(self):
        for name, expected in (('CODES', CAPTURE_DIAGNOSTIC_CODES),
                               ('STAGES', CAPTURE_DIAGNOSTIC_STAGES),
                               ('ERROR_TYPES', CAPTURE_DIAGNOSTIC_ERROR_TYPES)):
            match = re.search(r'const CAPTURE_' + name + r' = new Set\((\[[^;]+\])\);', SOURCE)
            self.assertIsNotNone(match, name)
            self.assertEqual(set(ast.literal_eval(match.group(1))), expected)

    @unittest.skipUnless(shutil.which('node'), 'JavaScript runtime is unavailable')
    def test_new_safe_stages_render_and_unknown_native_details_are_rejected(self):
        # Execute the actual formatter in isolation; no DOM, bridge or native
        # application exists in this test process.
        declarations = '\n'.join(re.findall(r'const CAPTURE_[A-Z_]+ = new Set\([^\n]+', SOURCE))
        formatter = re.search(r'  function captureDiagnostic\(error\) [^\n]+', SOURCE).group(0)
        inputs = [{'code': 'unexpected', 'stage': stage, 'error_type': 'runtime_error'}
                  for stage in ('ipc_read', 'worker_exit', 'worker_deadline',
                                'capture_freshness', 'worker_exit_freshness',
                                'preview_freshness', 'preview_geometry', 'preview_encoding')]
        inputs.append({'code': 'stale', 'stage': 'preview_freshness', 'error_type': 'value_error'})
        inputs += [{'code': 'unexpected', 'stage': '/private/user/window-title', 'error_type': 'runtime_error'},
                   {'code': '/private/user/window-title', 'stage': 'worker', 'error_type': 'runtime_error'}]
        script = declarations + '\n' + formatter + '\nconsole.log(JSON.stringify(' + json.dumps(inputs) + '.map(captureDiagnostic)));'
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True,
                                timeout=5, check=True)
        messages = json.loads(result.stdout)
        for value, message in zip(inputs[:8], messages[:8]):
            self.assertIn('at ' + value['stage'], message)
        self.assertIn('Capture a new preview', messages[8])
        self.assertNotRegex(messages[8], r'\d')
        self.assertEqual(messages[9:], ['Preview failed. No input was sent.'] * 2)
        self.assertNotIn('/private', result.stdout)


if __name__ == '__main__':
    unittest.main()
