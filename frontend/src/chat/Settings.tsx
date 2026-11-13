import type * as React from 'react';
import type { Options, Status } from '../api';
import type { Preferences } from '../App';
import { Button, SelectField, SliderField, SwitchField, ui } from '../ui/controls';
import styles from './Chat.module.css';

const CONTEXTS = [4096, 8192, 12288, 16384, 24576, 32768];

export function SettingsPanel({
  status,
  options,
  prefs,
  setPrefs,
}: {
  status: Status | null;
  options: Options;
  prefs: Preferences;
  setPrefs: React.Dispatch<React.SetStateAction<Preferences>>;
}) {
  const set = <K extends keyof Options>(key: K, value: Options[K]) =>
    setPrefs((p) => ({ ...p, options: { ...p.options, [key]: value } }));
  const installed = status?.ollama.models ?? [];
  const loaded = new Map(status?.ollama.loaded.map((m) => [m.name, m]) ?? []);
  const models = installed.includes(options.model) ? installed : [options.model, ...installed];
  const modelOptions = models.map((name) => {
    const inMemory = loaded.get(name);
    return {
      value: name,
      label: name,
      note: !installed.includes(name)
        ? 'not installed'
        : inMemory
          ? `loaded · ${inMemory.gpu_percent}% GPU`
          : undefined,
    };
  });
  const contextOptions = (CONTEXTS.includes(options.num_ctx) ? CONTEXTS : [...CONTEXTS, options.num_ctx])
    .sort((a, b) => a - b)
    .map((n) => ({ value: String(n), label: `${n.toLocaleString()} tokens` }));
  const missing = status?.ollama.ok && !installed.includes(options.model);
  const customised = Object.keys(prefs.options).length > 0;

  return (
    <div className={styles.Settings}>
      <div className={styles.Group}>
        <h2 className={styles.GroupTitle}>Local model</h2>
        <div className={styles.Field}>
          <SelectField label="Model" value={options.model} options={modelOptions} onChange={(v) => set('model', v)} />
          {missing && (
            <p className={styles.FieldWarning}>
              Not installed. Run <code>ollama pull {options.model}</code> in a terminal.
            </p>
          )}
        </div>
        <div className={styles.Field}>
          <SelectField
            label="Context length"
            value={String(options.num_ctx)}
            options={contextOptions}
            onChange={(v) => set('num_ctx', Number(v))}
          />
          <p className={ui.Hint}>Larger contexts use more GPU memory. Keep the model at 100% GPU.</p>
        </div>
        <SwitchField
          label="Search the wiki only (no model)"
          checked={prefs.searchOnly}
          onChange={(searchOnly) => setPrefs((p) => ({ ...p, searchOnly }))}
        />
      </div>
      <div className={styles.Group}>
        <h2 className={styles.GroupTitle}>Generation</h2>
        <SliderField
          label="Temperature"
          value={options.temperature}
          min={0}
          max={1}
          step={0.05}
          format={(v) => v.toFixed(2)}
          onChange={(v) => set('temperature', v)}
        />
        <SliderField
          label="Maximum answer length"
          value={options.output_tokens}
          min={200}
          max={4000}
          step={100}
          onChange={(v) => set('output_tokens', v)}
        />
      </div>
      <div className={styles.Group}>
        <h2 className={styles.GroupTitle}>Retrieval</h2>
        <SliderField
          label="Evidence budget"
          value={options.context_tokens}
          min={500}
          max={20000}
          step={500}
          onChange={(v) => set('context_tokens', v)}
        />
        <SliderField
          label="Passages per search"
          value={options.retrieval_limit}
          min={1}
          max={30}
          onChange={(v) => set('retrieval_limit', v)}
        />
        <SliderField
          label="Extra searches the model may run"
          value={options.search_rounds}
          min={0}
          max={3}
          onChange={(v) => set('search_rounds', v)}
        />
      </div>
      <div className={styles.Group} data-plain>
        <Button size="sm" disabled={!customised} onClick={() => setPrefs((p) => ({ ...p, options: {} }))}>
          Reset to .env defaults
        </Button>
        <p className={ui.Hint}>Search, embeddings and answers all run on this computer. No paid API is used.</p>
      </div>
    </div>
  );
}
