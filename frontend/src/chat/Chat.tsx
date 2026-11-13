import * as React from 'react';
import { ask, type Answer, type Options, type Status } from '../api';
import type { Preferences } from '../App';
import { Button, Confirm } from '../ui/controls';
import { ArrowUpIcon, SlidersIcon, StopIcon, TrashIcon } from '../ui/icons';
import { AnswerView, LiveAnswer } from './Message';
import { SettingsPanel } from './Settings';
import styles from './Chat.module.css';

export type ChatMessage =
  | { id: string; role: 'user'; content: string }
  | { id: string; role: 'assistant'; content: string; answer: Answer };

const SUGGESTIONS = [
  'How does the Electric Blast Furnace work?',
  'What progression leads to LuV?',
  'Which coils do I need for 1800 K recipes?',
  'How do I build a Cleanroom?',
];

const FALLBACK: Options = {
  model: 'qwen3.5:4b',
  num_ctx: 8192,
  temperature: 0.2,
  output_tokens: 1000,
  context_tokens: 5000,
  retrieval_limit: 8,
  search_rounds: 2,
};

interface Live {
  status: string;
  text: string;
}

const newId = () => Math.random().toString(36).slice(2) + Date.now().toString(36);

export function Chat({
  status,
  messages,
  setMessages,
  prefs,
  setPrefs,
  goToKnowledgeBase,
}: {
  status: Status | null;
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  prefs: Preferences;
  setPrefs: React.Dispatch<React.SetStateAction<Preferences>>;
  goToKnowledgeBase: () => void;
}) {
  const [draft, setDraft] = React.useState('');
  const [live, setLive] = React.useState<Live | null>(null);
  const [showSettings, setShowSettings] = React.useState(false);
  const abort = React.useRef<AbortController | null>(null);
  const scroller = React.useRef<HTMLDivElement>(null);
  const stick = React.useRef(true);

  const options: Options = { ...FALLBACK, ...status?.defaults, ...prefs.options };
  const busy = live !== null;
  const empty = status !== null && status.knowledge_base.chunks === 0;

  // Follow the stream unless the reader scrolled up to read something.
  React.useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages, live]);

  async function send(question: string) {
    question = question.trim();
    if (!question || busy) return;
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((m) => [...m, { id: newId(), role: 'user', content: question }]);
    setDraft('');
    stick.current = true;
    const controller = new AbortController();
    abort.current = controller;
    let text = '';
    let final: Answer | null = null;
    setLive({ status: 'Searching your wiki…', text: '' });
    try {
      await ask(
        { question, history, options, search_only: prefs.searchOnly },
        (event) => {
          if (event.type === 'status') setLive((l) => ({ text: l?.text ?? '', status: event.text }));
          else if (event.type === 'token') {
            text += event.text;
            setLive((l) => ({ status: l?.status ?? '', text }));
          } else if (event.type === 'reset') {
            text = '';
            setLive((l) => ({ status: l?.status ?? '', text: '' }));
          } else if (event.type === 'final') final = event.answer;
          else if (event.type === 'error') final = { text: event.message, sources: [] };
        },
        controller.signal,
      );
    } catch (error) {
      final = controller.signal.aborted
        ? { text: text || 'Stopped.', sources: [], warnings: ['Stopped before the answer was complete.'] }
        : { text: `Could not reach the local API (${(error as Error).message}).`, sources: [] };
    } finally {
      abort.current = null;
    }
    const answer: Answer = final ?? { text: 'No answer was returned.', sources: [] };
    setMessages((m) => [...m, { id: newId(), role: 'assistant', content: answer.text, answer }]);
    setLive(null);
  }

  return (
    <div className={styles.Layout} data-settings={showSettings || undefined}>
      <aside className={styles.Aside} aria-label="Model and retrieval settings">
        <SettingsPanel status={status} options={options} prefs={prefs} setPrefs={setPrefs} />
      </aside>
      <section className={styles.Main}>
        <div
          className={styles.Scroll}
          ref={scroller}
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
          }}
        >
          <div className={styles.Thread}>
            {empty && (
              <div className={styles.Notice}>
                Your knowledge base is empty. Collect and index wiki articles in{' '}
                <button type="button" className={styles.LinkButton} onClick={goToKnowledgeBase}>
                  Knowledge base
                </button>{' '}
                first.
              </div>
            )}
            {messages.length === 0 && !busy && (
              <div className={styles.Welcome}>
                <h1 className={styles.WelcomeTitle}>Ask the wiki</h1>
                <p className={styles.WelcomeText}>
                  Answers come only from your local copy of the GTNH wiki, with every fact cited. Nothing leaves
                  this computer.
                </p>
                <div className={styles.Suggestions}>
                  {SUGGESTIONS.map((s) => (
                    <button key={s} type="button" className={styles.Suggestion} onClick={() => send(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) =>
              m.role === 'user' ? (
                <div key={m.id} className={styles.Question}>
                  {m.content}
                </div>
              ) : (
                <AnswerView key={m.id} answer={m.answer} />
              ),
            )}
            {live && <LiveAnswer status={live.status} text={live.text} />}
          </div>
        </div>
        <form
          className={styles.Composer}
          onSubmit={(e) => {
            e.preventDefault();
            send(draft);
          }}
        >
          <div className={styles.ComposerBox}>
            <textarea
              className={styles.Textarea}
              value={draft}
              rows={1}
              placeholder={
                prefs.searchOnly ? 'Search the wiki (no model)…' : 'Ask about machines, materials, or progression…'
              }
              aria-label="Question"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send(draft);
                }
              }}
            />
            {busy ? (
              <Button variant="primary" size="icon" aria-label="Stop" onClick={() => abort.current?.abort()}>
                <StopIcon />
              </Button>
            ) : (
              <Button variant="primary" size="icon" type="submit" aria-label="Send" disabled={!draft.trim()}>
                <ArrowUpIcon />
              </Button>
            )}
          </div>
          <div className={styles.ComposerBar}>
            <span className={styles.ComposerHint}>
              {prefs.searchOnly ? 'Search only' : options.model} · Enter to send, Shift+Enter for a new line
            </span>
            <div className={styles.ComposerActions}>
              <Button
                variant="ghost"
                className={styles.SettingsToggle}
                aria-expanded={showSettings}
                onClick={() => setShowSettings((v) => !v)}
              >
                <SlidersIcon /> Settings
              </Button>
              {messages.length > 0 && (
                <Confirm
                  trigger={
                    <Button variant="ghost" disabled={busy}>
                      <TrashIcon /> Clear conversation
                    </Button>
                  }
                  title="Clear this conversation?"
                  description="The questions and answers are removed from this browser. Your wiki data is not affected."
                  action="Clear"
                  onConfirm={() => setMessages([])}
                />
              )}
            </div>
          </div>
        </form>
      </section>
    </div>
  );
}
