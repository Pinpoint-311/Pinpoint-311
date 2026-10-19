import { describe, it, expect } from 'vitest';
import { humanize, humanizeTitle, isEnumLike } from './humanize';

describe('humanize', () => {
    it('turns snake, kebab, dotted and camel values into sentence case', () => {
        expect(humanize('login_success')).toBe('Login success');
        expect(humanize('in_progress')).toBe('In progress');
        expect(humanize('push-status')).toBe('Push status');
        expect(humanize('setup.complete')).toBe('Setup complete');
        expect(humanize('pushStatus')).toBe('Push status');
    });

    it('spells known acronyms and names properly', () => {
        expect(humanize('public_api')).toBe('Public API');
        expect(humanize('send_sms')).toBe('Send SMS');
        expect(humanize('smtp')).toBe('SMTP');
        expect(humanize('arcgis_feature_layer')).toBe('ArcGIS feature layer');
        expect(humanize('google_secret_manager')).toBe('Google secret manager');
        expect(humanize('data_export_pii')).toBe('Data export PII');
        expect(humanize('oauth')).toBe('OAuth');
        expect(humanize('open311')).toBe('Open311');
    });

    it('reads SCREAMING_SNAKE keys as words', () => {
        expect(humanize('SMTP_PASSWORD')).toBe('SMTP password');
        expect(humanize('INSTALL_YEAR')).toBe('Install year');
    });

    it('is empty for null and undefined', () => {
        expect(humanize(null)).toBe('');
        expect(humanize(undefined)).toBe('');
    });

    it('title-cases proper names on request', () => {
        expect(humanizeTitle('google_maps')).toBe('Google Maps');
        expect(humanizeTitle('openai')).toBe('OpenAI');
    });
});

describe('isEnumLike', () => {
    it('accepts bare snake_case values only', () => {
        expect(isEnumLike('not_configured')).toBe(true);
        expect(isEnumLike('healthy')).toBe(false);
        expect(isEnumLike('REQ-2026-001')).toBe(false);
        expect(isEnumLike('/var/backups')).toBe(false);
        expect(isEnumLike(3)).toBe(false);
    });
});
