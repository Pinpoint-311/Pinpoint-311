import { useState } from 'react';
import { AlertTriangle, CheckCircle, RotateCcw } from 'lucide-react';
import { Modal, Button } from './ui';
import { api } from '../services/api';

/**
 * Restore one uploaded backup over the live database.
 *
 * The endpoint existed with no screen, so in an emergency the only way back was
 * a hand-written API call. Restoring is destructive and final for anything
 * written since the backup, so the dialog says exactly that and asks for the
 * word RESTORE. The server snapshots the current database first; the result
 * names that snapshot, which is the way back from restoring the wrong one.
 */
export default function BackupRestore({ name, createdAt }: { name: string; createdAt?: string }) {
    const [open, setOpen] = useState(false);
    const [typed, setTyped] = useState('');
    const [running, setRunning] = useState(false);
    const [result, setResult] = useState<{ ok: boolean; text: string; snapshot?: string } | null>(null);

    const close = () => {
        if (running) return;
        setOpen(false);
        setTyped('');
        setResult(null);
    };

    const run = async () => {
        setRunning(true);
        setResult(null);
        try {
            const r = await api.restoreBackup(name);
            setResult({
                ok: true,
                text: 'Database restored. Restart the backend and worker so every process reads the restored data.',
                snapshot: r.pre_restore_snapshot,
            });
        } catch (err: any) {
            setResult({ ok: false, text: err?.message || 'The restore did not complete. Nothing was changed if the snapshot step failed.' });
        } finally {
            setRunning(false);
        }
    };

    const when = createdAt ? new Date(createdAt).toLocaleString() : name;

    return (
        <>
            <button type="button" className="btn-outline btn-outline-danger" onClick={() => setOpen(true)}>
                <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
                Restore
            </button>
            <Modal isOpen={open} onClose={close} title="Restore this backup?" size="md">
                <div className="space-y-4 text-sm">
                    {!result?.ok && (
                        <>
                            <div className="flex items-start gap-3 rounded-xl border border-red-400/30 bg-red-500/10 p-3 text-red-100">
                                <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0 text-red-300" aria-hidden="true" />
                                <p>
                                    This replaces the entire database with the backup from <strong>{when}</strong>.
                                    Reports, comments, users and settings changed since then will be gone.
                                </p>
                            </div>
                            <ul className="list-disc pl-5 space-y-1 text-white/70">
                                <li>A snapshot of the current database is saved on the server first. If it can't be saved, nothing is restored.</li>
                                <li>Uploaded photos aren't part of database backups and stay as they are.</li>
                                <li>Restart the backend and worker afterwards.</li>
                            </ul>
                            <div>
                                <label htmlFor={`restore-confirm-${name}`} className="block text-white/80 mb-1">
                                    Type <span className="font-mono text-white">RESTORE</span> to confirm
                                </label>
                                <input
                                    id={`restore-confirm-${name}`}
                                    className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3 font-mono"
                                    value={typed}
                                    onChange={(e) => setTyped(e.target.value)}
                                    autoComplete="off"
                                    disabled={running}
                                />
                            </div>
                        </>
                    )}
                    {result && (
                        <div
                            role="status"
                            className={`flex items-start gap-3 rounded-xl border p-3 ${result.ok ? 'border-emerald-400/30 bg-emerald-500/10 text-emerald-100' : 'border-red-400/30 bg-red-500/10 text-red-100'}`}
                        >
                            {result.ok
                                ? <CheckCircle className="w-5 h-5 mt-0.5 shrink-0 text-emerald-300" aria-hidden="true" />
                                : <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0 text-red-300" aria-hidden="true" />}
                            <div>
                                <p>{result.text}</p>
                                {result.snapshot && (
                                    <p className="mt-1 text-xs text-white/60">Snapshot of the previous database: <span className="font-mono">{result.snapshot}</span></p>
                                )}
                            </div>
                        </div>
                    )}
                    <div className="flex justify-end gap-2">
                        <Button variant="ghost" onClick={close} disabled={running}>{result?.ok ? 'Close' : 'Cancel'}</Button>
                        {!result?.ok && (
                            <Button
                                onClick={run}
                                disabled={running || typed.trim() !== 'RESTORE'}
                                className="bg-red-600 hover:bg-red-700"
                            >
                                {running ? 'Restoring…' : 'Restore database'}
                            </Button>
                        )}
                    </div>
                </div>
            </Modal>
        </>
    );
}
