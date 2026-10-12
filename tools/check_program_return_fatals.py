# SPDX-License-Identifier: Apache-2.0
"""Bind native program-return controls to real, exact testbench fatal sites."""
import re


def require(condition, diagnostic):
    if not condition:
        raise ValueError('PROGRAM_RETURN_FATAL_' + diagnostic)


def fatal_sites(testbench, expected):
    """Skip comments and strings; accept only literal, unformatted fatal calls.

    Track named begin/end blocks in the standalone Testbench so an identically
    worded assertion in an unrelated scope cannot satisfy a control.
    """
    expected = set(expected)
    require(expected and all(isinstance(x, str) and x for x in expected), 'EXPECTED_MESSAGES')
    token = re.compile(r'//[^\n]*|/\*.*?\*/|\$fatal\s*\(\s*1\s*,\s*"([^"\\\r\n%]+)"\s*\)\s*;|"(?:\\.|[^"\\])*"|\bbegin\b(?:\s*:\s*(\w+))?|\bend\b', re.S)
    sites = []
    blocks = []
    for match in token.finditer(testbench):
        if re.match(r'begin\b', match[0]):
            blocks.append(match[2])
        elif match[0] == 'end':
            require(bool(blocks), 'UNBALANCED_END')
            blocks.pop()
        if match[1] in expected:
            sites.append(dict(source='testbench.sv', line=testbench.count('\n', 0, match.start()) + 1,
                              message=match[1], scope='.'.join(['Testbench'] + [b for b in blocks if b])))
    require(not blocks, 'UNBALANCED_BEGIN')
    require(bool(sites), 'NO_EXPECTED_ASSERTION_SITE')
    return sites


def classify_fatal(compiled, simulated, log, sites):
    require(compiled.get('exit_code') == 0 and not compiled.get('timed_out'), 'COMPILE_NOT_PASS')
    require(simulated.get('exit_code') == 1 and not simulated.get('timed_out'), 'SIMULATION_NOT_FAULT')
    require(not re.search(r'TIMEOUT|DEADLINE|CA_TEST_PASS|CONTRACT_PROBES_PASS|\bERROR\b|syntax error', log, re.I),
            'FORBIDDEN_RESULT')
    allowed = {(x['source'], x['line'], x['message'], x['scope']) for x in sites}
    require(bool(allowed), 'NO_ALLOWED_SITE')
    lines = log.splitlines()
    records = []
    for index, line in enumerate(lines):
        if 'fatal' not in line.lower():
            continue
        fatal = re.fullmatch(r'FATAL: ([^\r\n]+):(\d+): ([^\r\n]+)', line)
        require(fatal is not None and index + 1 < len(lines), 'MALFORMED_RECORD')
        context = re.fullmatch(r'\s+Time: (\d+)\s+Scope: ([A-Za-z_][\w.]*)\s*', lines[index + 1])
        require(context is not None, 'MISSING_CONTEXT')
        record = dict(source=fatal[1], line=int(fatal[2]), message=fatal[3], scope=context[2], time=int(context[1]))
        require((record['source'], record['line'], record['message'], record['scope']) in allowed,
                'UNEXPECTED_SITE:' + fatal[3])
        records.append(record)
    require(bool(records), 'NO_TARGET_FATAL')
    return records
