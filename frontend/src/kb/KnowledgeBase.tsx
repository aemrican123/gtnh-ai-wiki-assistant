import * as React from 'react';
import { Collapsible } from '@base-ui/react/collapsible';
import { Progress } from '@base-ui/react/progress';
import { Toast } from '@base-ui/react/toast';
import { api, type JobKind, type Status } from '../api';
import { Button, Confirm, NumberInput, ui } from '../ui/controls';
import { CaretRightIcon } from '../ui/icons';
import styles from './KnowledgeBase.module.css';

const ACTIONS: { kind: JobKind; label: string; hint: string }[] = [
  { kind: 'scrape', label: 'Collect / resume', hint: 'Fetch queued wiki pages, then index them.' },
  { kind: 'update', label: 'Update wiki', hint: 'Recheck saved pages for changes.' },
  { kind: 'index', label: 'Index pending', hint: 'Index collected articles that are not indexed yet.' },
];

export function KnowledgeBase({ status, reload }: { status: Status | null; reload: (refresh?: boolean) => void }) {
  const toasts = Toast.useToastManager();
  const [limit, setLimit] = React.useState(20);
  const [errors, setErrors] = React.useState<{ url: string; error: string }[] | null>(null);
  const [archive, setArchive] = React.useState('');
  const [destination, setDestination] = React.useState('');
  const wasRunning = React.useRef(false);

  const job = status?.job;
  const kb = status?.knowledge_base;
  const running = !!job && (job.running || job.external);

  React.useEffect(() => {
    if (!job) return;
    if (wasRunning.current && !job.running) {
      toasts.add(
        job.error
          ? { title: 'Job stopped with an error', description: job.error, type: 'error', timeout: 0 }
          : { title: job.message, description: 'Collection and index checkpoints are saved.' },
      );
    }
    wasRunning.current = job.running;
  }, [job, toasts]);

  async function run<T>(action: () => Promise<T>, success?: (value: T) => { title: string; description?: string }) {
    try {
      const value = await action();
      if (success) toasts.add(success(value));
    } catch (error) {
      toasts.add({ title: 'Could not complete that', description: (error as Error).message, type: 'error' });
    } finally {
      reload();
    }
  }

  if (!status || !kb || !job) return <div className={styles.Page}>Loading…</div>;

  const total = kb.done + kb.pending + kb.errors + kb.skipped;
  const percent = total ? Math.round((100 * kb.done) / total) : 0;
  const start = (kind: JobKind) => run(() => api.startJob(kind, limit || null));

  return (
    <div className={styles.Scroll}>
      <div className={styles.Page}>
        <div className={styles.Heading}>
          <h1 className={styles.Title}>Local knowledge base</h1>
          <p className={ui.Hint}>
            Embedding model (CPU): <code>{status.embedding_model}</code> · Data folder: <code>{status.data_dir}</code>
          </p>
        </div>

        <dl className={styles.Stats}>
          {[
            ['Articles', kb.articles],
            ['Indexed articles', kb.indexed_articles],
            ['Passages', kb.chunks],
            ['Queued URLs', kb.pending],
            ['Errors', kb.errors],
          ].map(([label, value]) => (
            <div key={label} className={styles.Stat} data-alert={label === 'Errors' && Number(value) > 0 || undefined}>
              <dt>{label}</dt>
              <dd>{Number(value).toLocaleString()}</dd>
            </div>
          ))}
        </dl>

        <section className={styles.Card}>
          <div className={styles.CardHead}>
            <h2 className={styles.CardTitle}>Collection</h2>
            <span className={styles.JobState} data-running={running || undefined}>
              {job.external ? 'Running in another process' : job.message}
            </span>
          </div>
          <Progress.Root className={ui.Progress} value={percent}>
            <Progress.Label className={ui.ProgressLabel}>
              {kb.done.toLocaleString()} of {total.toLocaleString()} known URLs collected
            </Progress.Label>
            <Progress.Value className={ui.ProgressValue} />
            <Progress.Track className={ui.ProgressTrack}>
              <Progress.Indicator className={ui.ProgressIndicator} />
            </Progress.Track>
          </Progress.Root>
          {job.external && job.progress && <p className={ui.Hint}>{job.progress}</p>}
          {job.error && (
            <div className={styles.Error} role="alert">
              {job.error}
            </div>
          )}
          <div className={styles.Controls}>
            <NumberInput label="Article limit (0 = all remaining)" value={limit} min={0} step={10} onChange={setLimit} />
            <div className={styles.Actions}>
              {ACTIONS.map((a) => (
                <Button key={a.kind} title={a.hint} disabled={running} onClick={() => start(a.kind)}>
                  {a.label}
                </Button>
              ))}
              <Confirm
                trigger={<Button disabled={running}>Rebuild index</Button>}
                title="Rebuild the whole index?"
                description="All saved articles are re-chunked and re-indexed from the content already on disk. Cached embeddings are reused, so nothing is downloaded, but it can take a while."
                action="Rebuild"
                onConfirm={() => start('rebuild')}
              />
              {job.running && (
                <Button variant="danger" onClick={() => run(api.cancelJob)}>
                  Cancel after current page
                </Button>
              )}
            </div>
          </div>
          <p className={ui.Hint}>
            Collection follows the wiki&rsquo;s sitemap and robots.txt with a polite rate limit, and saves a checkpoint
            after every page. Run only one app or command-line writer per data folder.
          </p>
          {job.result && !job.running && (
            <pre className={styles.Result}>{JSON.stringify(job.result, null, 2)}</pre>
          )}
        </section>

        {kb.errors > 0 && (
          <Collapsible.Root
            className={styles.Card}
            onOpenChange={(open) => {
              if (open) api.errors().then((r) => setErrors(r.errors), () => setErrors([]));
            }}
          >
            <Collapsible.Trigger className={styles.Disclosure}>
              <CaretRightIcon className={styles.Caret} />
              Collection errors ({kb.errors.toLocaleString()})
            </Collapsible.Trigger>
            <Collapsible.Panel className={styles.DisclosurePanel}>
              {errors === null ? (
                <p className={ui.Hint}>Loading…</p>
              ) : (
                <table className={styles.Table}>
                  <thead>
                    <tr>
                      <th>URL</th>
                      <th>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {errors.map((e) => (
                      <tr key={e.url}>
                        <td>
                          <a href={e.url} target="_blank" rel="noreferrer">
                            {decodeURI(e.url.replace(/^https?:\/\/[^/]+/, ''))}
                          </a>
                        </td>
                        <td>{e.error}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Collapsible.Panel>
          </Collapsible.Root>
        )}

        <section className={styles.Card}>
          <h2 className={styles.CardTitle}>Backup and restore</h2>
          <p className={ui.Hint}>
            Backups include original pages and cached embeddings. Your <code>.env</code> settings are excluded.
          </p>
          <div>
            <Button
              disabled={running}
              onClick={() => run(api.backup, (r) => ({ title: 'Backup saved', description: r.path }))}
            >
              Create backup
            </Button>
          </div>
          <div className={styles.RestoreGrid}>
            <label className={styles.InputField}>
              <span className={ui.Label}>Backup ZIP path</span>
              <input
                className={ui.Input}
                value={archive}
                placeholder="data\backups\gtnh-….zip"
                onChange={(e) => setArchive(e.target.value)}
              />
            </label>
            <label className={styles.InputField}>
              <span className={ui.Label}>Restore into an empty folder</span>
              <input
                className={ui.Input}
                value={destination}
                placeholder="C:\coding\wikiscraper\data-restored"
                onChange={(e) => setDestination(e.target.value)}
              />
            </label>
          </div>
          <div>
            <Button
              disabled={running || !archive.trim() || !destination.trim()}
              onClick={() =>
                run(
                  () => api.restore(archive.trim(), destination.trim()),
                  (r) => ({ title: 'Backup restored', description: r.message }),
                )
              }
            >
              Restore backup
            </Button>
          </div>
          <p className={ui.Hint}>Existing data is never overwritten: the destination folder must be empty.</p>
        </section>

        <p className={styles.Footer}>
          Wiki content: CC BY-SA 4.0 unless otherwise noted. This is an independent local assistant.
        </p>
      </div>
    </div>
  );
}
