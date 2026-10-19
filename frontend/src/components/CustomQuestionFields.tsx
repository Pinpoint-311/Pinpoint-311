import type { CustomQuestion } from '../types';

/**
 * The questions a municipality adds to a category, as form fields.
 *
 * Shared by the resident report form and the staff intake form so a category's
 * questions are asked -- and labelled, grouped and validated -- the same way
 * whichever door the report comes through. Answers are keyed by the question's
 * label, which is what the server stores in `custom_fields`; error messages are
 * keyed `custom_<question id>`, the same key the caller's error summary uses.
 */
interface CustomQuestionFieldsProps {
    questions: CustomQuestion[];
    answers: Record<string, string | string[]>;
    onChange: (label: string, value: string | string[]) => void;
    /** Messages keyed `custom_<question id>`. Other keys are ignored. */
    errors?: Record<string, string>;
    /** The control id for a question, so an error summary can link to it. */
    fieldId?: (questionId: string) => string;
    /** Prefix for radio-group names, so two forms on one page cannot collide. */
    namePrefix?: string;
}

const defaultFieldId = (questionId: string) => `field-custom-${questionId}`;

/** Whether a required question still has no answer. */
export function isUnanswered(answer: string | string[] | undefined): boolean {
    return answer === undefined || answer === '' || (Array.isArray(answer) && answer.length === 0);
}

export default function CustomQuestionFields({
    questions, answers, onChange, errors = {}, fieldId: idFor = defaultFieldId, namePrefix = 'custom_',
}: CustomQuestionFieldsProps) {
    return (
        <>
        {/* Each question is rendered from a clerk-authored
            definition, so nothing here can rely on hand-written
            markup being right. Every control gets an id that its
            <label> (or <legend>) points at, and the error message
            gets an id the control points back at -- the same
            association ui/Input.tsx already makes. Before this,
            the label was floating text, so each field was
            announced as "edit, blank" with the placeholder read
            as if it were the question (WCAG 1.3.1, 3.3.1,
            3.3.2, 4.1.2). */}
        {questions.map((q) => {
            const fieldId = idFor(q.id);
            const errorId = `${fieldId}-error`;
            const error = errors[`custom_${q.id}`];
            const describedBy = error ? errorId : undefined;
            const labelText = (
                <>
                    {q.label}
                    {q.required && <span className="text-red-400" aria-hidden="true"> *</span>}
                    {q.required && <span className="sr-only"> (required)</span>}
                </>
            );
            /* Plain text, not role="alert": the control
               above points at it with aria-describedby, so
               it is read on focus, and the error summary
               that takes focus on a failed submit already
               speaks every message once. As an alert each
               question added another region firing in the
               same commit as the summary, and a pile of
               simultaneous alerts announces as nothing. */
            const errorNode = error ? (
                <p id={errorId} className="text-red-400 text-sm">
                    {error}
                </p>
            ) : null;

            /* Radios, checkboxes and yes/no are groups of controls
               answering one question, which is what fieldset and
               legend are for. As bare divs the question text was
               not attached to the options at all, so a screen
               reader read "Yes" and "No" with nothing saying what
               was being asked. Native grouping, not role= --
               fieldset/legend needs no ARIA to say the same thing. */
            if (q.type === 'radio' || q.type === 'checkbox' || q.type === 'yes_no') {
                const multi = q.type === 'checkbox';
                const options = q.type === 'yes_no' ? ['Yes', 'No'] : (q.options ?? []);
                const selected = answers[q.label];
                return (
                    <fieldset
                        key={q.id}
                        id={fieldId}
                        tabIndex={-1}
                        aria-describedby={describedBy}
                        className="space-y-2 m-0 p-0 border-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70 rounded-lg"
                    >
                        <legend className="block text-sm font-medium text-white/70 mb-2">
                            {labelText}
                        </legend>
                        <div className={q.type === 'yes_no' ? 'flex gap-3' : 'space-y-2'}>
                            {options.map(opt => {
                                /* Selection used to be a background colour on a
                                   <button> and nothing else: invisible to a screen
                                   reader, and gone entirely in forced-colours mode
                                   (WCAG 1.4.1, 4.1.2). A real radio carries its own
                                   state, its own focus ring and its own arrow-key
                                   behaviour, so no aria-pressed is needed. */
                                const checked = multi
                                    ? ((selected as string[] | undefined) ?? []).includes(opt)
                                    : selected === opt;
                                return (
                                    <label
                                        key={opt}
                                        className={`flex items-center gap-3 text-white/80 cursor-pointer ${q.type === 'yes_no'
                                            ? `flex-1 justify-center py-2 rounded-lg border transition-colors ${checked
                                                ? 'bg-primary-500/30 border-primary-500 text-white'
                                                : 'bg-white/5 border-white/20 hover:border-white/40'}`
                                            : ''}`}
                                    >
                                        <input
                                            type={multi ? 'checkbox' : 'radio'}
                                            name={multi ? undefined : `${namePrefix}${q.id}`}
                                            value={opt}
                                            checked={checked}
                                            onChange={(e) => {
                                                if (!multi) {
                                                    onChange(q.label, opt);
                                                    return;
                                                }
                                                const current = (answers[q.label] as string[]) || [];
                                                const updated = e.target.checked
                                                    ? [...current, opt]
                                                    : current.filter(v => v !== opt);
                                                onChange(q.label, updated);
                                            }}
                                            className={`w-4 h-4 accent-primary-500 ${multi ? 'rounded' : ''}`}
                                        />
                                        <span>{opt}</span>
                                    </label>
                                );
                            })}
                        </div>
                        {errorNode}
                    </fieldset>
                );
            }

            return (
                <div key={q.id} className="space-y-2">
                    <label htmlFor={fieldId} className="block text-sm font-medium text-white/70">
                        {labelText}
                    </label>

                    {/* Text Input */}
                    {q.type === 'text' && (
                        <input
                            id={fieldId}
                            type="text"
                            placeholder={q.placeholder || ''}
                            value={(answers[q.label] as string) || ''}
                            onChange={(e) => onChange(q.label, e.target.value)}
                            className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3"
                            required={q.required}
                            aria-required={q.required || undefined}
                            aria-invalid={error ? 'true' : undefined}
                            aria-describedby={describedBy}
                        />
                    )}

                    {/* Textarea */}
                    {q.type === 'textarea' && (
                        <textarea
                            id={fieldId}
                            rows={3}
                            placeholder={q.placeholder || ''}
                            value={(answers[q.label] as string) || ''}
                            onChange={(e) => onChange(q.label, e.target.value)}
                            className="w-full rounded-lg bg-white/10 border border-white/20 text-white px-3 py-2"
                            required={q.required}
                            aria-required={q.required || undefined}
                            aria-invalid={error ? 'true' : undefined}
                            aria-describedby={describedBy}
                        />
                    )}

                    {/* Number */}
                    {q.type === 'number' && (
                        <input
                            id={fieldId}
                            type="number"
                            placeholder={q.placeholder || ''}
                            value={(answers[q.label] as string) || ''}
                            onChange={(e) => onChange(q.label, e.target.value)}
                            className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3"
                            required={q.required}
                            aria-required={q.required || undefined}
                            aria-invalid={error ? 'true' : undefined}
                            aria-describedby={describedBy}
                        />
                    )}

                    {/* Date */}
                    {q.type === 'date' && (
                        <input
                            id={fieldId}
                            type="date"
                            value={(answers[q.label] as string) || ''}
                            onChange={(e) => onChange(q.label, e.target.value)}
                            className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3"
                            required={q.required}
                            aria-required={q.required || undefined}
                            aria-invalid={error ? 'true' : undefined}
                            aria-describedby={describedBy}
                        />
                    )}

                    {/* Select Dropdown. The aria-label it used to carry is
                        gone: it now has a real <label>, and an aria-label
                        alongside one silently wins over it. */}
                    {q.type === 'select' && (
                        <select
                            id={fieldId}
                            value={(answers[q.label] as string) || ''}
                            onChange={(e) => onChange(q.label, e.target.value)}
                            className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3"
                            required={q.required}
                            aria-required={q.required || undefined}
                            aria-invalid={error ? 'true' : undefined}
                            aria-describedby={describedBy}
                        >
                            <option value="">Select...</option>
                            {q.options?.map(opt => (
                                <option key={opt} value={opt}>{opt}</option>
                            ))}
                        </select>
                    )}

                    {errorNode}
                </div>
            );
        })}
        </>
    );
}
