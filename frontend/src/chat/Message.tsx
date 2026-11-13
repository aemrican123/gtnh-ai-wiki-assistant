import * as React from 'react';
import Markdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Collapsible } from '@base-ui/react/collapsible';
import type { Answer, Source } from '../api';
import { Tip } from '../ui/controls';
import { CaretRightIcon } from '../ui/icons';
import styles from './Message.module.css';

const CITATION = /^S\d+$/;

/** Model output is untrusted: no raw HTML, and only links the app itself produced are clickable. */
function components(sources: Source[]): Components {
  const byId = new Map(sources.map((s) => [s.id, s]));
  return {
    a({ href, children }) {
      const label = String(React.Children.toArray(children).join(''));
      if (CITATION.test(label)) {
        const source = byId.get(label);
        if (!source) return <span className={styles.Cite}>{label}</span>;
        return (
          <Tip
            content={
              <>
                <strong>{source.title}</strong>
                {source.section && <> · {source.section}</>}
              </>
            }
          >
            <a className={styles.Cite} href={source.url} target="_blank" rel="noreferrer">
              {label}
            </a>
          </Tip>
        );
      }
      const known = sources.some((s) => s.url === href);
      return known ? (
        <a href={href} target="_blank" rel="noreferrer">
          {children}
        </a>
      ) : (
        <span>{children}</span>
      );
    },
    img: () => null,
  };
}

function Prose({ text, sources }: { text: string; sources: Source[] }) {
  // While streaming, citations arrive as bare [S1]; give them a link target so they render as chips.
  const prepared = text.replace(/\[(S\d+)\](?!\()/g, '[$1](#$1)');
  const parts = React.useMemo(() => components(sources), [sources]);
  return (
    <div className={styles.Prose}>
      <Markdown remarkPlugins={[remarkGfm]} components={parts} skipHtml>
        {prepared}
      </Markdown>
    </div>
  );
}

function seconds(ms: number) {
  return `${(ms / 1000).toFixed(1)} s`;
}

function Metrics({ answer }: { answer: Answer }) {
  if (!answer.calls) return null;
  const parts = [answer.model];
  if (answer.tokens_per_second) parts.push(`${answer.tokens_per_second.toFixed(1)} tok/s`);
  if (answer.first_token_ms != null) parts.push(`first token ${seconds(answer.first_token_ms)}`);
  if ((answer.load_ms ?? 0) > 500) parts.push(`model load ${seconds(answer.load_ms!)}`);
  parts.push(`retrieval ${Math.round(answer.retrieval_ms ?? 0)} ms`);
  parts.push(`${(answer.input_tokens ?? 0).toLocaleString()} in · ${(answer.output_tokens ?? 0).toLocaleString()} out`);
  if (answer.calls > 1) parts.push(`${answer.calls} model calls`);
  return <div className={styles.Metrics}>{parts.join(' · ')}</div>;
}

function Evidence({ sources }: { sources: Source[] }) {
  if (!sources.length) return null;
  return (
    <Collapsible.Root className={styles.Evidence}>
      <Collapsible.Trigger className={styles.EvidenceTrigger}>
        <CaretRightIcon className={styles.EvidenceCaret} />
        Retrieved evidence ({sources.length})
      </Collapsible.Trigger>
      <Collapsible.Panel className={styles.EvidencePanel}>
        <ol className={styles.SourceList}>
          {sources.map((s) => (
            <li key={s.id} className={styles.Source} id={s.id}>
              <div className={styles.SourceHead}>
                <span className={styles.Cite}>{s.id}</span>
                <a href={s.url} target="_blank" rel="noreferrer" className={styles.SourceTitle}>
                  {s.title}
                </a>
                {s.section && <span className={styles.SourceSection}>{s.section}</span>}
              </div>
              <pre className={styles.SourceText}>{s.text}</pre>
            </li>
          ))}
        </ol>
      </Collapsible.Panel>
    </Collapsible.Root>
  );
}

export function AnswerView({ answer }: { answer: Answer }) {
  return (
    <article className={styles.Answer}>
      <Prose text={answer.text} sources={answer.sources} />
      {answer.warnings?.map((w) => (
        <div key={w} className={styles.Warning} role="note">
          {w}
        </div>
      ))}
      <Metrics answer={answer} />
      <Evidence sources={answer.sources} />
    </article>
  );
}

export function LiveAnswer({ status, text }: { status: string; text: string }) {
  return (
    <article className={styles.Answer} aria-busy="true">
      <div className={styles.Activity} role="status">
        <span className={styles.Spinner} aria-hidden="true" />
        {status}
      </div>
      {text && <Prose text={text + ' ▍'} sources={[]} />}
    </article>
  );
}
