#!/usr/bin/env node
// Turn @axe-core/cli --save output into a JUnit report, so GitLab shows the
// accessibility audit in merge requests and the pipeline's Tests tab.
//
//   node scripts/axe-junit.mjs accessibility-*.json > accessibility-junit.xml
//
// One test suite per audited page, one test case per axe rule that applied to
// it: a passing rule is a passing case, a violated rule is a failure listing
// each offending element. Prints a summary to stderr and exits 1 when any page
// has a violation, 2 when a page could not be audited at all (no results file,
// or one that is not axe output), so the CI job can flag either.

import { readFileSync } from 'node:fs';
import { basename } from 'node:path';

const xml = (s) => String(s ?? '')
    // Characters XML 1.0 cannot carry at all, then the five it must escape.
    .replace(/[^\x09\x0A\x0D\x20-퟿-�\u{10000}-\u{10FFFF}]/gu, '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&apos;');

const files = process.argv.slice(2);
if (files.length === 0) {
    console.error('usage: axe-junit.mjs <axe-results.json>...');
    process.exit(2);
}

let violations = 0;
let broken = 0;
const suites = [];

for (const file of files) {
    const page = basename(file, '.json').replace(/^accessibility-/, '');
    let results;
    try {
        results = JSON.parse(readFileSync(file, 'utf8'));
        if (!Array.isArray(results) || results.length === 0) throw new Error('no axe results');
    } catch (err) {
        broken += 1;
        console.error(`${page}: could not read ${file}: ${err.message}`);
        suites.push(
            `  <testsuite name="${xml(page)}" tests="1" failures="0" errors="1">\n` +
            `    <testcase classname="axe.${xml(page)}" name="audit ran">\n` +
            `      <error message="${xml(err.message)}"/>\n` +
            '    </testcase>\n  </testsuite>');
        continue;
    }
    for (const result of results) {
        const cases = [];
        for (const rule of result.passes ?? []) {
            cases.push(`    <testcase classname="axe.${xml(page)}" name="${xml(`${rule.id}: ${rule.help}`)}"/>`);
        }
        for (const rule of result.violations ?? []) {
            violations += 1;
            const nodes = (rule.nodes ?? []).map((n) =>
                `${[].concat(n.target ?? []).join(' ')}\n  ${(n.failureSummary ?? '').replace(/\n/g, '\n  ')}`);
            cases.push(
                `    <testcase classname="axe.${xml(page)}" name="${xml(`${rule.id}: ${rule.help}`)}">\n` +
                `      <failure type="${xml(rule.impact ?? 'violation')}" message="${xml(`${rule.help} (${rule.nodes?.length ?? 0} element(s))`)}">` +
                `${xml(`${rule.helpUrl}\n\n${nodes.join('\n\n')}`)}</failure>\n` +
                '    </testcase>');
        }
        const failed = (result.violations ?? []).length;
        console.error(`${page} (${result.url}): ${(result.passes ?? []).length} passes, ${failed} violations`);
        suites.push(
            `  <testsuite name="${xml(`${page} ${result.url}`)}" tests="${cases.length}" failures="${failed}" errors="0">\n` +
            `${cases.join('\n')}\n  </testsuite>`);
    }
}

process.stdout.write(`<?xml version="1.0" encoding="UTF-8"?>\n<testsuites name="axe-core WCAG 2.1 AA">\n${suites.join('\n')}\n</testsuites>\n`);
process.exit(broken ? 2 : violations ? 1 : 0);
