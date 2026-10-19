import { useId, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { Checkbox } from './ui';

/**
 * Which service categories something applies to: a map layer's assets, the
 * reports a polygon layer is recorded on, the residents who see its outlines.
 *
 * The value is a list of service codes, and an empty list means every
 * category -- including ones added later -- which is what the server and the
 * resident portal have always taken it to mean. So the picker leads with that
 * choice ("All categories" / "Only some") rather than a bare checkbox list,
 * where nothing ticked would read as "nothing".
 *
 * Searchable, because a town can have forty-odd categories. Codes in the value
 * that the list does not know (a category since switched off) are kept as they
 * are: this picker never drops what it cannot show.
 */

export interface CategoryOption {
    service_code: string;
    service_name: string;
}

interface Props {
    /** Visible label; the group's accessible name. */
    label: string;
    /** One short line under the label. */
    description?: string;
    services: CategoryOption[];
    /** Service codes; empty = all categories. */
    value: string[];
    onChange: (codes: string[]) => void;
    disabled?: boolean;
    /** Said in place of the description while disabled, and why. */
    disabledReason?: string | null;
    loading?: boolean;
}

/** "All categories", "3 of 42 categories". */
export function categoryScopeSummary(value: string[], services: CategoryOption[]): string {
    if (value.length === 0) return 'All categories';
    const known = new Set(services.map(s => s.service_code));
    const n = value.filter(c => known.has(c)).length;
    return `${n} of ${services.length} ${services.length === 1 ? 'category' : 'categories'}`;
}

export function CategoryScopePicker({
    label, description, services, value, onChange, disabled = false, disabledReason, loading = false,
}: Props) {
    const id = useId();
    const [choosing, setChoosing] = useState(false);
    const [query, setQuery] = useState('');
    const some = value.length > 0 || choosing;

    const shown = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return services;
        return services.filter(s => s.service_name.toLowerCase().includes(q) || s.service_code.toLowerCase().includes(q));
    }, [services, query]);

    const toggle = (code: string, on: boolean) => {
        onChange(on ? [...value, code] : value.filter(c => c !== code));
    };
    const selectShown = () => {
        const add = shown.map(s => s.service_code).filter(c => !value.includes(c));
        onChange([...value, ...add]);
    };
    const clearShown = () => {
        const drop = new Set(shown.map(s => s.service_code));
        onChange(value.filter(c => !drop.has(c)));
    };

    const helpId = `${id}-help`;
    const summaryId = `${id}-summary`;
    const help = disabled && disabledReason ? disabledReason : description;
    const summary = some && value.length === 0
        ? 'None ticked yet: saves as all categories.'
        : categoryScopeSummary(value, services);

    return (
        <fieldset
            disabled={disabled}
            aria-describedby={[help ? helpId : '', summaryId].filter(Boolean).join(' ')}
            className="min-w-0 space-y-3"
        >
            <legend className="text-sm font-medium text-white">{label}</legend>
            {/* The reason stays at full contrast; only the controls dim. */}
            {help && <p id={helpId} className={`-mt-1 text-xs ${disabled && disabledReason ? 'text-amber-200' : 'text-white/70'}`}>{help}</p>}

            <div className={`space-y-3 ${disabled ? 'opacity-50' : ''}`}>
                <div className="grid grid-cols-2 gap-1 rounded-xl bg-white/5 p-1 border border-white/15">
                    {([['all', 'All categories'], ['some', 'Only some']] as const).map(([mode, text]) => {
                        const on = mode === 'some' ? some : !some;
                        return (
                            <label
                                key={mode}
                                className={`flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm cursor-pointer transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-[3px] has-[:focus-visible]:outline-amber-300 ${on ? 'bg-primary-500/40 text-white font-medium shadow-sm' : 'text-white/75 hover:bg-white/10'}`}
                            >
                                <input
                                    type="radio"
                                    name={`${id}-mode`}
                                    className="sr-only"
                                    checked={on}
                                    onChange={() => {
                                        if (mode === 'all') { setChoosing(false); onChange([]); }
                                        else setChoosing(true);
                                    }}
                                />
                                {text}
                            </label>
                        );
                    })}
                </div>

                {some && (
                    <div className="space-y-2">
                        <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                            <div className="relative flex-1 min-w-0">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/50 pointer-events-none z-10" aria-hidden="true" />
                                <input
                                    type="search"
                                    value={query}
                                    onChange={e => setQuery(e.target.value)}
                                    aria-label={`Search categories for ${label.toLowerCase()}`}
                                    placeholder="Search categories"
                                    className="glass-input !py-2 pl-9 text-sm w-full"
                                />
                            </div>
                            <div className="flex gap-2 shrink-0">
                                <button type="button" className="btn-outline" onClick={selectShown} disabled={shown.length === 0}>
                                    {query.trim() ? 'Select shown' : 'Select all'}
                                </button>
                                <button type="button" className="btn-outline" onClick={clearShown} disabled={value.length === 0}>
                                    {query.trim() ? 'Clear shown' : 'Clear'}
                                </button>
                            </div>
                        </div>
                        {loading && services.length === 0 ? (
                            <p className="text-sm text-white/70 p-3 rounded-lg bg-white/5 border border-white/10">Loading categories…</p>
                        ) : shown.length === 0 ? (
                            <p className="text-sm text-white/70 p-3 rounded-lg bg-white/5 border border-white/10">
                                {services.length === 0 ? 'No categories yet.' : `No category matches "${query.trim()}".`}
                            </p>
                        ) : (
                            <ul className="grid grid-cols-1 sm:grid-cols-2 gap-0.5 max-h-64 overflow-y-auto p-1.5 rounded-lg bg-black/10 border border-white/10">
                                {shown.map(s => (
                                    <li key={s.service_code}>
                                        <label className="flex items-start gap-2.5 rounded-md px-2 py-1.5 text-sm text-white/85 cursor-pointer hover:bg-white/10">
                                            <Checkbox
                                                checked={value.includes(s.service_code)}
                                                onChange={e => toggle(s.service_code, e.target.checked)} />
                                            <span className="min-w-0 break-words">{s.service_name}</span>
                                        </label>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                )}
            </div>

            <p id={summaryId} className="text-xs font-medium text-white/70">{summary}</p>
        </fieldset>
    );
}

export default CategoryScopePicker;
