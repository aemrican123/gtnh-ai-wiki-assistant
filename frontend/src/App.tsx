import * as React from 'react';
import { Tabs } from '@base-ui/react/tabs';
import { Toast } from '@base-ui/react/toast';
import { Tooltip } from '@base-ui/react/tooltip';
import { api, type Options, type Status } from './api';
import { Chat, type ChatMessage } from './chat/Chat';
import { KnowledgeBase } from './kb/KnowledgeBase';
import { useStored } from './storage';
import { Button, Tip, Toasts } from './ui/controls';
import { GearIcon, RefreshIcon, SunMoonIcon } from './ui/icons';
import styles from './App.module.css';

export interface Preferences {
  options: Partial<Options>;
  searchOnly: boolean;
}

type Theme = 'system' | 'light' | 'dark';

function useStatus() {
  const [status, setStatus] = React.useState<Status | null>(null);
  const [offline, setOffline] = React.useState(false);
  const load = React.useCallback(async (refresh = false) => {
    try {
      setStatus(await api.status(refresh));
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);
  const running = !!status && (status.job.running || status.job.external);
  React.useEffect(() => {
    load();
    // Poll quickly while a job runs so progress stays live; slowly otherwise.
    const timer = window.setInterval(() => load(), running ? 2000 : 8000);
    return () => window.clearInterval(timer);
  }, [load, running]);
  return { status, offline, reload: load };
}

export function App() {
  const { status, offline, reload } = useStatus();
  const [tab, setTab] = useStored<'ask' | 'kb'>('gtnh.tab', 'ask');
  const [theme, setTheme] = useStored<Theme>('gtnh.theme', 'system');
  const [messages, setMessages] = useStored<ChatMessage[]>('gtnh.messages', []);
  const [prefs, setPrefs] = useStored<Preferences>('gtnh.preferences', { options: {}, searchOnly: false });

  React.useEffect(() => {
    if (theme === 'system') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
  }, [theme]);

  const nextTheme: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' };

  return (
    <Toast.Provider timeout={6000}>
      <Tooltip.Provider delay={300}>
        <Tabs.Root className={styles.Shell} value={tab} onValueChange={(v) => setTab(v as 'ask' | 'kb')}>
          <header className={styles.Header}>
            <div className={styles.Brand}>
              <span className={styles.BrandMark}>
                <GearIcon />
              </span>
              <div>
                <div className={styles.BrandName}>GTNH Field Guide</div>
                <div className={styles.BrandTag}>Local wiki companion · from steam to the Stargate</div>
              </div>
            </div>
            <Tabs.List className={styles.TabList}>
              <Tabs.Tab className={styles.Tab} value="ask">
                Ask the wiki
              </Tabs.Tab>
              <Tabs.Tab className={styles.Tab} value="kb">
                Knowledge base
                {status && (status.job.running || status.job.external) && <span className={styles.LiveDot} />}
              </Tabs.Tab>
              <Tabs.Indicator className={styles.TabIndicator} />
            </Tabs.List>
            <div className={styles.HeaderEnd}>
              <StatusPills status={status} offline={offline} />
              <Tip content="Check Ollama again">
                <Button variant="ghost" size="icon-sm" aria-label="Refresh status" onClick={() => reload(true)}>
                  <RefreshIcon />
                </Button>
              </Tip>
              <Tip content={`Theme: ${theme}`}>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Theme: ${theme}. Switch to ${nextTheme[theme]}`}
                  onClick={() => setTheme(nextTheme[theme])}
                >
                  <SunMoonIcon />
                </Button>
              </Tip>
            </div>
          </header>
          {offline && (
            <div className={styles.Banner} role="alert">
              The local API is not responding. Is <code>start_gtnh.bat</code> still running?
            </div>
          )}
          <Tabs.Panel className={styles.Panel} value="ask">
            <Chat
              status={status}
              messages={messages}
              setMessages={setMessages}
              prefs={prefs}
              setPrefs={setPrefs}
              goToKnowledgeBase={() => setTab('kb')}
            />
          </Tabs.Panel>
          <Tabs.Panel className={styles.Panel} value="kb">
            <KnowledgeBase status={status} reload={reload} />
          </Tabs.Panel>
        </Tabs.Root>
        <Toasts />
      </Tooltip.Provider>
    </Toast.Provider>
  );
}

function StatusPills({ status, offline }: { status: Status | null; offline: boolean }) {
  if (offline) return <span className={styles.Pill} data-state="error">API offline</span>;
  if (!status) return <span className={styles.Pill}>Connecting…</span>;
  const { ollama, knowledge_base: kb } = status;
  const loaded = ollama.loaded[0];
  return (
    <div className={styles.Pills}>
      <Tip content={ollama.ok ? `Ollama at ${ollama.host}` : (ollama.error ?? 'Ollama is not reachable')}>
        <span className={styles.Pill} data-state={ollama.ok ? 'ok' : 'error'}>
          <span className={styles.Dot} />
          {ollama.ok ? `Ollama ${ollama.version}` : 'Ollama offline'}
        </span>
      </Tip>
      {loaded && (
        <Tip
          content={`${loaded.name} in memory: ${loaded.vram_gb.toFixed(1)} of ${loaded.size_gb.toFixed(1)} GB on the GPU. Below 100% the model partly runs on the CPU and is much slower.`}
        >
          <span className={styles.Pill} data-state={loaded.gpu_percent >= 100 ? 'ok' : 'warn'}>
            <span className={styles.Dot} />
            {loaded.gpu_percent}% GPU
          </span>
        </Tip>
      )}
      {ollama.gpu && (
        <Tip content={`${ollama.gpu.name} · ${ollama.gpu.utilization_percent}% busy`}>
          <span className={`${styles.Pill} ${styles.Optional}`}>
            {(ollama.gpu.memory_used_mb / 1024).toFixed(1)} / {(ollama.gpu.memory_total_mb / 1024).toFixed(1)} GB
            VRAM
          </span>
        </Tip>
      )}
      <Tip content={`${kb.indexed_articles.toLocaleString()} of ${kb.articles.toLocaleString()} articles indexed`}>
        <span className={styles.Pill} data-state={kb.chunks ? undefined : 'warn'}>
          {kb.chunks.toLocaleString()} passages
        </span>
      </Tip>
    </div>
  );
}
