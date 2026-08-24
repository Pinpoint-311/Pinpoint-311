import type { Capability } from '../services/api';

/**
 * What a deployment gives back, and which box each value belongs in.
 *
 * The templates were the easy half. A town pressed Deploy, Azure created seven
 * resources and printed seven values, and then the operator was on their own:
 * find the AI card, find the right box, retype an endpoint; find the Translation
 * card, retype a region. Made, but not connected. This file is the other half --
 * one paste, distributed to the boxes the values belong to.
 *
 * The mapping is deliberately data rather than code. Each entry names an output
 * exactly as the template emits it and the credential keys it fills, so the
 * whole contract between a template and the cards is one table a reviewer can
 * read. backend/tests/test_deploy_templates.py holds the other end of it: every
 * output labelled `Pinpoint box: <label>` must name a label a catalog really
 * has, so an output that stops matching anything is a failing test rather than
 * a box nobody can find.
 *
 * Two rules, both learned from the failure this replaces:
 *
 *   * An output that matches nothing is REPORTED, not dropped. It means the
 *     template and the catalogs have drifted, which is a bug, and swallowing it
 *     turns that bug into "some of my boxes filled in and I don't know why".
 *   * Nothing is saved silently. What matched, what did not, and what is still
 *     missing is on screen before anything is written.
 */

/** One value a deployment emits, and where it goes. */
export interface OutputMapping {
    /** The output's name, exactly as the template emits it. */
    output: string;
    /** Credential keys it fills. More than one where the same value serves two
     *  boxes -- Azure's multi-service account is one endpoint for Vision and
     *  Face both. */
    keys: string[];
    /** Human name for the value, for the matched/unmatched list. */
    label: string;
    /**
     * The capability this value belongs to, and the provider it implies.
     *
     * Pasting a deployment's outputs used to write the secrets and stop there,
     * so a town could paste an Azure vault's URL and key name, see every box
     * turn green, and still be encrypting with Google -- the credentials were
     * saved and the decision to use them was not. The switch has to be part of
     * the same action, because from the operator's side it WAS one action.
     *
     * Named per mapping rather than derived from the cloud, because the
     * provider id is not the cloud id: AWS's key management is `aws` and its AI
     * is `bedrock`. Guessing that mapping is how a switch lands on a provider
     * nobody chose.
     *
     * Absent means the value belongs to no capability's selection -- a region
     * that several providers read, say -- and only the secret is written.
     */
    select?: { capability: string; provider: string };
}

/**
 * A credential the deployment deliberately does not give back.
 *
 * Both templates emit no key, password or secret, because deployment history is
 * readable by more people than the person deploying. That is a good decision
 * with a bad failure mode: the operator pastes the outputs, sees boxes still
 * empty, and concludes the paste did not work. So the ones that are still a
 * human's job are listed by name, with where each one lives.
 */
export interface ManualCredential {
    key: string;
    label: string;
    /** Where to get it. One clause, no navigation essay. */
    where: string;
    /** Which card it belongs to, so the list groups the way the page does. */
    cap: Capability;
}

export interface CloudOutputs {
    /** What the operator is copying, named the way their console names it. */
    sourceLabel: string;
    /** One line on where to find it in that console. */
    sourceHint: string;
    mappings: OutputMapping[];
    manual: ManualCredential[];
}

export const DEPLOY_OUTPUTS: Record<string, CloudOutputs> = {
    azure: {
        sourceLabel: 'the deployment Outputs',
        sourceHint: 'Resource group → Deployments → your deployment → Outputs. Select the list and copy it, or paste the JSON view — either works.',
        mappings: [
            { output: 'keyVaultUrl', keys: ['AZURE_KEYVAULT_URL'], label: 'Key Vault URL', select: { capability: 'kms', provider: 'azure' } },
            { output: 'keyName', keys: ['AZURE_KEYVAULT_KEY'], label: 'Key name' },
            { output: 'directoryTenantId', keys: ['AZURE_TENANT_ID'], label: 'Directory (tenant) ID' },
            { output: 'azureOpenAiEndpoint', keys: ['AZURE_OPENAI_ENDPOINT'], label: 'Azure OpenAI endpoint', select: { capability: 'ai', provider: 'azure' } },
            { output: 'azureOpenAiDeploymentName', keys: ['AZURE_OPENAI_DEPLOYMENT'], label: 'Deployment name' },
            // One multi-service account serves both, which is the whole reason
            // the template creates one account rather than three.
            { output: 'aiServicesEndpoint', keys: ['AZURE_VISION_ENDPOINT', 'AZURE_FACE_ENDPOINT'], label: 'AI Services endpoint', select: { capability: 'redaction', provider: 'azure' } },
            { output: 'translatorRegion', keys: ['AZURE_TRANSLATOR_REGION'], label: 'Translator region', select: { capability: 'translation', provider: 'azure' } },
        ],
        manual: [
            { key: 'AZURE_KEYVAULT_CLIENT_ID', label: 'Application (client) ID', where: 'Entra ID → App registrations → your app → Overview', cap: 'kms' },
            { key: 'AZURE_KEYVAULT_CLIENT_SECRET', label: 'Client secret', where: 'the same app → Certificates & secrets. Shown once', cap: 'kms' },
            { key: 'AZURE_OPENAI_API_KEY', label: 'Azure OpenAI key', where: 'the OpenAI account → Keys and Endpoint', cap: 'ai' },
            { key: 'AZURE_TRANSLATOR_KEY', label: 'Translator key', where: 'the AI Services account → Keys and Endpoint', cap: 'translation' },
            { key: 'AZURE_VISION_KEY', label: 'Vision key', where: 'the same AI Services account, same key', cap: 'redaction' },
            { key: 'AZURE_FACE_KEY', label: 'Face key', where: 'the same AI Services account, same key', cap: 'redaction' },
        ],
    },
    aws: {
        sourceLabel: 'the stack Outputs',
        sourceHint: 'CloudFormation → your stack → Outputs. Copy the JSON, or the two values below.',
        mappings: [
            { output: 'PinpointBoxAwsRegion', keys: ['AWS_REGION'], label: 'AWS Region' },
            { output: 'PinpointBoxKeyIdOrArn', keys: ['AWS_KMS_KEY_ID'], label: 'Key ID or ARN', select: { capability: 'kms', provider: 'aws' } },
        ],
        // Nothing. The stack creates a role, not a key, which is the point of
        // it: on AWS compute there is no credential to enter anywhere.
        manual: [],
    },
};

/** A value the paste produced, and what became of it. */
export interface MatchedOutput {
    output: string;
    label: string;
    value: string;
    keys: string[];
    /** Carried through from the mapping so the caller can switch the capability
     *  in the same action that saves the value. See OutputMapping.select. */
    select?: { capability: string; provider: string };
}

export interface ParsedOutputs {
    matched: MatchedOutput[];
    /** Outputs the template gave back that no box wanted. Reported, never
     *  dropped: on a real deployment this means drift between the template and
     *  the catalogs, which somebody needs to know about. */
    unmatched: { output: string; value: string }[];
    /** Boxes this cloud's outputs should have filled and did not, because the
     *  paste did not contain them -- an unticked toggle at deploy time, most
     *  often, which is worth saying rather than leaving as an empty box. */
    absent: OutputMapping[];
    /** Why nothing could be read, when nothing could. */
    error: string | null;
}

const EMPTY: ParsedOutputs = { matched: [], unmatched: [], absent: [], error: null };

/**
 * Flatten whatever the operator pasted into `{name: value}`.
 *
 * Four shapes reach this, because two consoles and two command lines all call
 * the same thing by a different name:
 *
 *   * Azure's portal and `az deployment group show`: `{"keyVaultUrl": {"type":
 *     "String", "value": "..."}}`, sometimes still wrapped in
 *     `{"properties": {"outputs": {...}}}`.
 *   * CloudFormation: `[{"OutputKey": "...", "OutputValue": "..."}]`, wrapped
 *     in `{"Stacks": [{"Outputs": [...]}]}` from `describe-stacks`.
 *   * A plain `{"name": "value"}`, which is what somebody produces by hand.
 *
 * Accepting all four costs twenty lines and removes the single most likely way
 * for this to fail in front of somebody -- pasting the right thing from the
 * wrong screen.
 */
function flatten(raw: unknown): Record<string, string> | null {
    if (raw === null || typeof raw !== 'object') return null;

    // describe-stacks
    const stacks = (raw as Record<string, unknown>).Stacks;
    if (Array.isArray(stacks) && stacks.length > 0) return flatten(stacks[0]);

    const outputsField = (raw as Record<string, unknown>).Outputs
        ?? (raw as Record<string, unknown>).outputs
        ?? ((raw as Record<string, unknown>).properties as Record<string, unknown> | undefined)?.outputs;
    if (outputsField !== undefined && outputsField !== raw) {
        const inner = flatten(outputsField);
        if (inner) return inner;
    }

    // CloudFormation's array of pairs.
    if (Array.isArray(raw)) {
        const flat: Record<string, string> = {};
        for (const entry of raw) {
            if (entry && typeof entry === 'object') {
                const k = (entry as Record<string, unknown>).OutputKey;
                const v = (entry as Record<string, unknown>).OutputValue;
                if (typeof k === 'string' && typeof v === 'string') flat[k] = v;
            }
        }
        return Object.keys(flat).length > 0 ? flat : null;
    }

    const flat: Record<string, string> = {};
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
        if (typeof v === 'string' || typeof v === 'number') {
            flat[k] = String(v);
        } else if (v && typeof v === 'object' && 'value' in (v as Record<string, unknown>)) {
            const inner = (v as Record<string, unknown>).value;
            if (typeof inner === 'string' || typeof inner === 'number') flat[k] = String(inner);
        }
    }
    return Object.keys(flat).length > 0 ? flat : null;
}

/**
 * Read a pasted outputs blob against one cloud's mapping.
 *
 * Never throws and never half-reports: a blob it cannot read comes back as an
 * error with nothing matched, so the caller has one thing to render rather than
 * a partial result to reason about.
 */

/**
 * The portal's Outputs tab, copied as it appears on screen.
 *
 * The instruction here used to say "copy the JSON", and on Azure there is no
 * JSON to copy: the Outputs tab renders one row per output, each with its own
 * copy button beside it, and selecting the tab gives you the names and values
 * as plain lines. So the only thing a reader could paste was the only thing
 * this rejected, and the message told them to go and find a blob that screen
 * does not offer.
 *
 * Three shapes, all of which a console or a CLI actually produces:
 *
 *     keyVaultUrl                 name and value on one line
 *     https://…                   (the portal, stacked)
 *
 *     keyVaultUrl: https://…      a colon, equals or tab between them
 *
 * A line starts a new value only when it matches a name this cloud declares.
 * That is what makes the stacked form unambiguous: `eastus` is shaped exactly
 * like an identifier, and guessing by shape would read it as the start of the
 * next pair rather than as the value of the last one. It also means a wrapped
 * prose value -- readMeFirst is a paragraph -- rejoins instead of truncating at
 * the first newline.
 */
function parseKeyValueLines(spec: CloudOutputs, text: string): Record<string, string> {
    const known = new Set<string>([
        ...spec.mappings.map(m => m.output.toLowerCase()),
        ...IGNORED,
    ]);
    const out: Record<string, string> = {};
    let current: string | null = null;
    let buffer: string[] = [];

    const commit = () => {
        if (current !== null) out[current] = buffer.join(' ').trim();
        current = null;
        buffer = [];
    };

    for (const raw of text.split(/\r?\n/)) {
        const line = raw.trim();
        if (!line) continue;

        const inline = line.match(/^([A-Za-z][A-Za-z0-9_]*)\s*[:=\t]\s*(.+)$/);
        if (inline && known.has(inline[1].toLowerCase())) {
            commit();
            out[inline[1]] = inline[2].trim().replace(/^["']|["'],?$/g, '');
            continue;
        }
        if (known.has(line.toLowerCase())) {
            commit();
            current = line;
            continue;
        }
        if (current !== null) buffer.push(line);
    }
    commit();
    return out;
}

export function parseDeployOutputs(cloud: string, text: string): ParsedOutputs {
    const spec = DEPLOY_OUTPUTS[cloud];
    if (!spec) return EMPTY;
    if (!text.trim()) return EMPTY;

    let flat: Record<string, string> | null = null;
    try {
        flat = flatten(JSON.parse(text));
    } catch {
        // Not JSON, which is the ordinary case rather than the error case: see
        // parseKeyValueLines. Only if that finds nothing either is this a paste
        // from the wrong screen.
        flat = null;
    }
    if (!flat || Object.keys(flat).length === 0) {
        const lines = parseKeyValueLines(spec, text);
        if (Object.keys(lines).length > 0) flat = lines;
    }
    if (!flat || Object.keys(flat).length === 0) {
        return { ...EMPTY, error: 'No output values in there. Copy the deployment\u2019s Outputs \u2014 the names and their values \u2014 rather than its summary.' };
    }

    // Names are compared case-insensitively. The two consoles disagree with
    // their own CLIs about capitalisation often enough that a correct paste
    // failing on a capital letter is a real outcome, and there is no output
    // whose meaning depends on its case.
    const byLowerName = new Map<string, string>();
    for (const [k, v] of Object.entries(flat)) byLowerName.set(k.toLowerCase(), v);

    const matched: MatchedOutput[] = [];
    const absent: OutputMapping[] = [];
    const consumed = new Set<string>();

    for (const mapping of spec.mappings) {
        const value = byLowerName.get(mapping.output.toLowerCase());
        if (value === undefined || value === '') {
            absent.push(mapping);
            continue;
        }
        consumed.add(mapping.output.toLowerCase());
        matched.push({
            output: mapping.output, label: mapping.label, value,
            keys: mapping.keys, select: mapping.select,
        });
    }

    const unmatched = Object.entries(flat)
        // `readMeFirst` is prose the template prints deliberately, not a value
        // anybody needs to place. Reporting it as drift would cry wolf on every
        // single paste, which is how a drift report stops being read.
        .filter(([k]) => !consumed.has(k.toLowerCase()) && !IGNORED.has(k.toLowerCase()))
        .map(([output, value]) => ({ output, value }));

    /* A paste with nothing in it we recognise is almost always the wrong
     * screen -- the deployment summary, the parameters, the activity log. The
     * unmatched list below says what was in there, but on its own it reads as
     * "seven bugs" rather than "wrong blob", so say which it is. */
    if (matched.length === 0) {
        return {
            matched, unmatched, absent,
            error: 'No Outputs values in there. Copy the deployment\u2019s Outputs, not its summary.',
        };
    }

    return { matched, unmatched, absent, error: null };
}

const IGNORED = new Set(['readmefirst', 'keyarn', 'rolearntoattach', 'instanceprofilename']);

/** The values a set of matches would write, as `{credentialKey: value}`. */
export function outputsToValues(matched: MatchedOutput[]): Record<string, string> {
    const values: Record<string, string> = {};
    for (const m of matched) for (const key of m.keys) values[key] = m.value;
    return values;
}


/**
 * The provider selections a set of matched outputs implies, deduplicated.
 *
 * `{capability: provider}`, so the caller makes one call per capability rather
 * than one per value -- Azure's AI Services endpoint fills two boxes and must
 * not select the same capability twice.
 */
export function selectionsFor(matched: MatchedOutput[]): Record<string, string> {
    const out: Record<string, string> = {};
    for (const m of matched) {
        if (m.select) out[m.select.capability] = m.select.provider;
    }
    return out;
}
