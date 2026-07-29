import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Check, Plus, SignpostBig, X } from 'lucide-react';

import { api } from '../services/api';

/**
 * Pick roads for a routing rule, from the roads this town actually has.
 *
 * The old control was a bare textarea of comma-separated names. A clerk typed
 * "County Route 516" from memory while the road data called it "Cranbury Rd",
 * the rule matched nothing, and it failed silently forever -- no error, no
 * warning, just a jurisdiction rule that never fired.
 *
 * Suggestions come from the town's own road table, so whatever is picked is
 * guaranteed to match at runtime. Free text is still allowed, because the road
 * table may not be seeded yet and a clerk should never be blocked by our data;
 * it is just marked as unverified so they can see the difference.
 */

interface RoadOption {
    name: string;
    ref: string | null;
    segments: number;
}

interface RoadListInputProps {
    /** Comma-separated, matching how routing_config stores these. */
    value: string;
    onChange: (value: string) => void;
    label: string;
    hint?: string;
    tone?: 'danger' | 'success';
    id?: string;
}

const splitRoads = (value: string): string[] =>
    value.split(',').map(part => part.trim()).filter(Boolean);

export default function RoadListInput({
    value, onChange, label, hint, tone = 'danger', id,
}: RoadListInputProps) {
    const roads = splitRoads(value);
    const [query, setQuery] = useState('');
    const [options, setOptions] = useState<RoadOption[]>([]);
    const [open, setOpen] = useState(false);
    const [dataAvailable, setDataAvailable] = useState<boolean | null>(null);
    const [knownNames, setKnownNames] = useState<Set<string>>(new Set());
    const [activeIndex, setActiveIndex] = useState(-1);
    const containerRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const searchSeq = useRef(0);

    const accent = tone === 'danger' ? 'text-red-300' : 'text-emerald-300';
    
    // Verify roads in list against searchRoads API
    useEffect(() => {
        roads.forEach(road => {
            const low = road.toLowerCase();
            if (!knownNames.has(low)) {
                api.searchRoads(road).then(res => {
                    if (res.roads.some(r => r.name.toLowerCase() === low || r.name.toLowerCase().includes(low))) {
                        setKnownNames(prev => new Set(prev).add(low));
                    }
                }).catch(() => {});
            }
        });
    }, [roads]);

    const listboxId = `${id || 'roadlist'}-options`;

    // Pull a first page on mount purely to learn whether road data exists at
    // all -- that decides between "no matches" and "we cannot check yet", which
    // are very different messages to show a clerk.
    useEffect(() => {
        let cancelled = false;
        api.searchRoads('')
            .then(result => {
                if (cancelled) return;
                setDataAvailable(result.available);
                setKnownNames(new Set(result.roads.map(r => r.name.toLowerCase())));
            })
            .catch(() => !cancelled && setDataAvailable(false));
        return () => { cancelled = true; };
    }, []);

    useEffect(() => {
        if (!query.trim()) { setOptions([]); return; }
        const seq = ++searchSeq.current;
        const timer = setTimeout(() => {
            api.searchRoads(query)
                .then(result => {
                    // Discard a slower earlier keystroke's results.
                    if (seq !== searchSeq.current) return;
                    setOptions(result.roads);
                    setActiveIndex(result.roads.length ? 0 : -1);
                    setKnownNames(prev => {
                        const next = new Set(prev);
                        result.roads.forEach(r => next.add(r.name.toLowerCase()));
                        return next;
                    });
                })
                .catch(() => seq === searchSeq.current && setOptions([]));
        }, 180);
        return () => clearTimeout(timer);
    }, [query]);

    useEffect(() => {
        const onDocumentClick = (event: MouseEvent) => {
            if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
        };
        document.addEventListener('mousedown', onDocumentClick);
        return () => document.removeEventListener('mousedown', onDocumentClick);
    }, []);

    const addRoad = useCallback((name: string) => {
        const trimmed = name.trim();
        if (!trimmed) return;
        if (roads.some(r => r.toLowerCase() === trimmed.toLowerCase())) {
            setQuery('');
            return;
        }
        onChange([...roads, trimmed].join(', '));
        setQuery('');
        setOptions([]);
        setActiveIndex(-1);
        inputRef.current?.focus();
    }, [roads, onChange]);

    const removeRoadByIndex = (index: number) => {
        const next = roads.filter((_, idx) => idx !== index);
        onChange(next.join(', '));
    };

    const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            setOpen(true);
            setActiveIndex(i => Math.min(i + 1, options.length - 1));
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            setActiveIndex(i => Math.max(i - 1, 0));
        } else if (event.key === 'Enter') {
            event.preventDefault();
            addRoad(activeIndex >= 0 && options[activeIndex] ? options[activeIndex].name : query);
        } else if (event.key === 'Escape') {
            setOpen(false);
        } else if (event.key === 'Backspace' && !query && roads.length) {
            removeRoadByIndex(roads.length - 1);
        }
    };

    // Only claim a road is unrecognised when we actually have data to check
    // against. Warning against an empty table would train clerks to ignore it.
    const isUnverified = (name: string) => {
        if (dataAvailable !== true || knownNames.size === 0) return false;
        const low = name.toLowerCase().trim();
        if (knownNames.has(low)) return false;
        for (const known of knownNames) {
            if (known.includes(low) || low.includes(known)) return false;
        }
        return true;
    };

    return (
        <div className="space-y-2" ref={containerRef}>
            <label htmlFor={id} className={`block text-sm font-medium ${accent}`}>{label}</label>

            <div className="rounded-xl bg-white/[0.06] border border-white/15 focus-within:border-primary-400/60 focus-within:ring-1 focus-within:ring-primary-400/30 transition-colors px-2.5 py-2">
                {roads.length > 0 && (
                    <ul className="flex flex-wrap gap-1.5 mb-2" aria-label={`${label} selections`}>
                        {roads.map((name, index) => (
                            <li key={`${name}-${index}`}>
                                <span className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 border border-white/15 pl-2.5 pr-1 py-1 text-sm text-white">
                                    <SignpostBig className="w-3.5 h-3.5 text-white/40" aria-hidden="true" />
                                    {name}
                                    {isUnverified(name) && (
                                        <AlertTriangle
                                            className="w-3.5 h-3.5 text-amber-400"
                                            aria-label="Not found in this town's road data"
                                        />
                                    )}
                                    <button
                                        type="button"
                                        onClick={() => removeRoadByIndex(index)}
                                        aria-label={`Remove ${name}`}
                                        className="p-1 rounded hover:bg-white/15 text-white/50 hover:text-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400"
                                    >
                                        <X className="w-3 h-3" aria-hidden="true" />
                                    </button>
                                </span>
                            </li>
                        ))}
                    </ul>
                )}

                <div className="relative">
                    <input
                        id={id}
                        ref={inputRef}
                        type="text"
                        role="combobox"
                        aria-expanded={open && options.length > 0}
                        aria-controls={listboxId}
                        aria-autocomplete="list"
                        aria-activedescendant={activeIndex >= 0 ? `${listboxId}-${activeIndex}` : undefined}
                        value={query}
                        onChange={e => { setQuery(e.target.value); setOpen(true); }}
                        onFocus={() => setOpen(true)}
                        onKeyDown={onKeyDown}
                        placeholder={roads.length ? 'Add another road…' : 'Start typing a road name…'}
                        className="w-full bg-transparent text-white placeholder-white/30 px-1 py-1.5 focus:outline-none"
                    />

                    {open && options.length > 0 && (
                        <ul
                            id={listboxId}
                            role="listbox"
                            aria-label="Matching roads"
                            className="absolute z-30 left-0 right-0 mt-1 max-h-64 overflow-auto rounded-xl border border-white/15 bg-slate-900/95 backdrop-blur-xl shadow-2xl shadow-black/40 py-1"
                        >
                            {options.map((option, index) => {
                                const already = roads.some(r => r.toLowerCase() === option.name.toLowerCase());
                                return (
                                    <li
                                        key={`${option.name}-${option.ref ?? ''}`}
                                        id={`${listboxId}-${index}`}
                                        role="option"
                                        aria-selected={index === activeIndex}
                                    >
                                        <button
                                            type="button"
                                            onMouseEnter={() => setActiveIndex(index)}
                                            onClick={() => addRoad(option.name)}
                                            className={`w-full text-left px-3 py-2 flex items-center justify-between gap-3 transition-colors ${
                                                index === activeIndex ? 'bg-white/10' : 'hover:bg-white/[0.06]'
                                            }`}
                                        >
                                            <span className="min-w-0">
                                                <span className="block text-sm text-white truncate">{option.name}</span>
                                                <span className="block text-[11px] text-white/40">
                                                    {option.ref ? `${option.ref} · ` : ''}
                                                    {option.segments} segment{option.segments === 1 ? '' : 's'}
                                                </span>
                                            </span>
                                            {already
                                                ? <Check className="w-4 h-4 text-emerald-400 shrink-0" aria-hidden="true" />
                                                : <Plus className="w-4 h-4 text-white/30 shrink-0" aria-hidden="true" />}
                                        </button>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </div>
            </div>

            {hint && <p className="text-xs text-white/40">{hint}</p>}

            {dataAvailable === false && (
                <p className="text-xs text-amber-300/80">
                    Road data hasn&apos;t been loaded for this town yet, so names can&apos;t be
                    checked. They&apos;ll still work once it loads — spelling just isn&apos;t verified.
                </p>
            )}
            {roads.some(isUnverified) && (
                <p className="text-xs text-amber-300/80">
                    Roads marked <AlertTriangle className="w-3 h-3 inline -mt-0.5" aria-hidden="true" /> aren&apos;t
                    in this town&apos;s road data. A rule for a road that doesn&apos;t match anything never applies.
                </p>
            )}
        </div>
    );
}
