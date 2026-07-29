#!/usr/bin/env node
/**
 * Emit the third-party license notices that must travel with the compiled bundle.
 *
 * The frontend ships as a container image serving a minified build. That bundle
 * contains the code of every production dependency, and MIT/ISC/BSD each require
 * their copyright notice to accompany "all copies or substantial portions" of the
 * software. A minified bundle is a copy, so the notices have to ship with it --
 * keeping them only in the repository does not discharge the obligation.
 *
 * Output lands in public/, which Vite copies verbatim into dist/, so nginx serves
 * it at /third-party-licenses.txt.
 *
 * Runs automatically via the `prebuild` npm script, so it cannot be forgotten:
 * every `npm run build`, local or in Docker, regenerates it from the actual
 * installed tree rather than from a list someone has to remember to update.
 */

import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, readdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(ROOT, 'public', 'third-party-licenses.txt');

/** Collect every production dependency name from the resolved npm tree. */
function productionDependencies() {
    const raw = execFileSync(
        'npm',
        ['ls', '--omit=dev', '--all', '--json', '--long=false'],
        { cwd: ROOT, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 },
    );
    const names = new Set();
    const walk = (deps) => {
        for (const [name, node] of Object.entries(deps || {})) {
            if (node.dev || node.extraneous) continue;
            names.add(name);
            walk(node.dependencies);
        }
    };
    walk(JSON.parse(raw).dependencies);
    return [...names].sort();
}

/** The verbatim LICENSE file a package ships, if it ships one. */
function licenseText(pkgDir) {
    let entries;
    try {
        entries = readdirSync(pkgDir);
    } catch {
        return null;
    }
    // Match LICENSE, LICENCE, LICENSE-MIT, COPYING, and friends -- but not
    // LICENSES.md-style indexes of other people's licenses.
    const file = entries.find((e) => /^(LICEN[CS]E|COPYING)(-\w+)?(\.\w+)?$/i.test(e));
    if (!file) return null;
    try {
        return readFileSync(join(pkgDir, file), 'utf8').trim();
    } catch {
        return null;
    }
}

const names = productionDependencies();
const sections = [];
const missing = [];

for (const name of names) {
    const pkgDir = join(ROOT, 'node_modules', ...name.split('/'));
    const manifestPath = join(pkgDir, 'package.json');
    if (!existsSync(manifestPath)) {
        missing.push(`${name} (not installed on this platform)`);
        continue;
    }
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
    const declared =
        typeof manifest.license === 'string'
            ? manifest.license
            : manifest.license?.type || manifest.licenses?.[0]?.type || 'UNDECLARED';
    const text = licenseText(pkgDir);
    if (!text) missing.push(`${name}@${manifest.version} (${declared}; ships no LICENSE file)`);

    sections.push(
        [
            '='.repeat(78),
            `${name}@${manifest.version}`,
            `License: ${declared}`,
            manifest.homepage ? `Homepage: ${manifest.homepage}` : null,
            '='.repeat(78),
            '',
            text || `[This package ships no LICENSE file. Declared license: ${declared}.]`,
            '',
        ]
            .filter((l) => l !== null)
            .join('\n'),
    );
}

const header = `Pinpoint 311 -- Third-Party Licenses (compiled frontend bundle)

Pinpoint 311 itself is licensed under the MIT License. This file lists the
third-party packages whose code is compiled into the JavaScript bundle served
by this application, together with their license texts.

It is generated at build time from the actual installed dependency tree, so it
describes this exact build rather than a hand-maintained list.

Packages: ${names.length}
${missing.length ? `\nNo LICENSE file found in the distribution for:\n${missing.map((m) => `  - ${m}`).join('\n')}\nTheir declared license is recorded in the section for each package below.\n` : ''}
Fonts loaded at runtime from Google Fonts (Inter, SIL Open Font License 1.1)
are not bundled and are noted in the project's THIRD-PARTY-NOTICES.md.

When served as a container image, that image derives from nginx:alpine, whose
base layer includes BusyBox (GPL-2.0) alongside musl (MIT) and nginx itself
(BSD-2-Clause). That layer is unmodified upstream; corresponding source is
published by Alpine Linux at https://gitlab.alpinelinux.org/alpine/aports

Full analysis, including runtime data sources and packages with incomplete
license metadata, is in THIRD-PARTY-NOTICES.md in the project repository:
https://github.com/Pinpoint-311/Pinpoint-311

`;

writeFileSync(OUT, header + '\n' + sections.join('\n'), 'utf8');
console.log(
    `third-party-licenses.txt: ${names.length} production packages` +
        (missing.length ? `, ${missing.length} without a LICENSE file` : ''),
);
