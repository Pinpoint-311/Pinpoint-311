import { useMemo, useState } from 'react';
import { Search, Sparkles, X } from 'lucide-react';

import {
    CATEGORY_ICON_GROUPS, categoryIconFor, searchCategoryIcons, suggestCategoryIcon,
    type CategoryIconDef,
} from './categoryIcons';

/**
 * Picks a service-category icon from the shared municipal set.
 * Search by what the category is about ("snow", "permit", "graffiti"), or take
 * the suggestion made from the category's name.
 */
export default function CategoryIconPicker({ value, onChange, categoryName }: {
    value: string;
    onChange: (name: string) => void;
    categoryName?: string;
}) {
    const [query, setQuery] = useState('');
    const suggested = useMemo(() => suggestCategoryIcon(categoryName), [categoryName]);
    const results = useMemo(() => (query.trim() ? searchCategoryIcons(query) : null), [query]);
    const SelectedIcon = categoryIconFor(value);

    const tile = (def: CategoryIconDef) => {
        const Icon = def.icon;
        const selected = value === def.name;
        return (
            <button
                type="button"
                key={def.name}
                onClick={() => onChange(def.name)}
                aria-pressed={selected}
                aria-label={def.label}
                title={def.label}
                className={`aspect-square rounded-xl transition-all duration-200 flex items-center justify-center ${selected
                    ? 'bg-gradient-to-r from-primary-500 to-indigo-600 text-white shadow-lg shadow-primary-500/40 ring-2 ring-white/30'
                    : 'bg-white/5 text-white/65 hover:bg-white/15 hover:text-white'}`}
            >
                <Icon className="w-4 h-4" aria-hidden="true" />
            </button>
        );
    };

    return (
        <div className="space-y-3">
            <div className="flex items-center gap-3">
                <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-primary-500/30 to-indigo-600/20 border border-primary-400/30 flex items-center justify-center shrink-0">
                    <SelectedIcon className="w-5 h-5 text-white" aria-hidden="true" />
                </div>
                <div className="relative flex-1 min-w-0">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" aria-hidden="true" />
                    <input
                        type="text"
                        value={query}
                        onChange={e => setQuery(e.target.value)}
                        placeholder="Search icons: snow, permit, graffiti…"
                        aria-label="Search icons"
                        className="w-full h-10 rounded-xl bg-white/[0.06] border border-white/15 text-sm text-white placeholder-white/35 pl-9 pr-8 focus:outline-none focus:border-primary-400/60"
                    />
                    {query && (
                        <button type="button" onClick={() => setQuery('')} aria-label="Clear icon search"
                            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-white/40 hover:text-white">
                            <X className="w-4 h-4" aria-hidden="true" />
                        </button>
                    )}
                </div>
            </div>

            {suggested && suggested !== value && !query && (() => {
                const def = searchCategoryIcons('').find(d => d.name === suggested)!;
                const Icon = def.icon;
                return (
                    <button
                        type="button"
                        onClick={() => onChange(def.name)}
                        className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl bg-primary-500/10 border border-primary-400/25 text-left hover:bg-primary-500/15 transition-colors"
                    >
                        <Sparkles className="w-3.5 h-3.5 text-primary-300 shrink-0" aria-hidden="true" />
                        <span className="text-xs text-white/60">Suggested for this category:</span>
                        <Icon className="w-4 h-4 text-white" aria-hidden="true" />
                        <span className="text-xs font-medium text-white">{def.label}</span>
                    </button>
                );
            })()}

            <div className="max-h-72 overflow-y-auto pr-1 space-y-3 rounded-2xl bg-white/[0.03] border border-white/10 p-3">
                {results ? (
                    results.length ? (
                        <div className="grid grid-cols-8 sm:grid-cols-10 gap-1.5">{results.map(tile)}</div>
                    ) : (
                        <p className="text-xs text-white/45 py-2 text-center">No icons match "{query}".</p>
                    )
                ) : (
                    CATEGORY_ICON_GROUPS.map(group => (
                        <div key={group.id}>
                            <p className="text-[11px] font-semibold uppercase tracking-wider text-white/40 mb-1.5">{group.label}</p>
                            <div className="grid grid-cols-8 sm:grid-cols-10 gap-1.5">{group.icons.map(tile)}</div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}
