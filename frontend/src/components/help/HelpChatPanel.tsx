"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { askHelp, HelpChatResponse } from "../../lib/api";

export function HelpChatPanel({
  tenantId,
  initialOpen = false,
}: {
  tenantId: string;
  initialOpen?: boolean;
}) {
  const [open, setOpen] = useState(initialOpen);
  const [question, setQuestion] = useState("");
  const [lastQuestion, setLastQuestion] = useState("");
  const [result, setResult] = useState<HelpChatResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    // Tenant changes must clear the prior tenant's local conversation state.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional tenant-scope reset
    setQuestion("");
    setLastQuestion("");
    setResult(null);
    setError(null);
    setPending(false);
  }, [tenantId]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || pending) return;
    const controller = new AbortController();
    controllerRef.current?.abort();
    controllerRef.current = controller;
    setPending(true);
    setError(null);
    setLastQuestion(trimmed);
    try {
      const response = await askHelp(tenantId, trimmed, undefined, controller.signal);
      if (!controller.signal.aborted) setResult(response);
    } catch (caught) {
      if (!controller.signal.aborted) {
        setError(caught instanceof Error ? caught.message : "Documentation help is unavailable.");
        setResult(null);
      }
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }

  function cancel() {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setPending(false);
    setError(null);
  }

  function retry() {
    setQuestion(lastQuestion);
    void submit({ preventDefault() {}, currentTarget: null } as unknown as FormEvent<HTMLFormElement>);
  }

  return (
    <div className="help-chat">
      <button
        type="button"
        className="help-chat__trigger help-chat__trigger--floating"
        aria-label={open ? "Close documentation help" : "Open documentation help"}
        aria-expanded={open}
        aria-controls="documentation-help"
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden="true">?</span>
        <span className="sr-only">Documentation help</span>
      </button>

      {open ? (
        <section id="documentation-help" className="help-chat__panel" role="dialog" aria-label="Documentation help">
          <div className="help-chat__heading">
            <div>
              <h2>Documentation help</h2>
              <p>Ask about RECLAIM contracts, safety boundaries, and operator workflows.</p>
            </div>
            <button type="button" className="icon-button" aria-label="Close documentation help" onClick={() => setOpen(false)}>×</button>
          </div>
          <p className="help-chat__notice"><strong>Advisory only.</strong> This assistant cannot inspect cases or execute actions. Answers are grounded in reviewed documentation.</p>
          <form className="help-chat__form" onSubmit={submit}>
            <label htmlFor="documentation-question">Question</label>
            <textarea
              id="documentation-question"
              aria-label="Documentation question"
              value={question}
              maxLength={2000}
              rows={3}
              placeholder="How are webhook correlations verified?"
              onChange={(event) => setQuestion(event.target.value)}
              disabled={pending}
            />
            <div className="help-chat__form-actions">
              <span className="help-chat__counter">{question.length}/2000</span>
              {pending ? <button type="button" className="button button--quiet" onClick={cancel}>Cancel</button> : null}
              <button type="submit" className="button button--primary" disabled={pending || !question.trim()}>{pending ? "Checking…" : "Ask help"}</button>
            </div>
          </form>

          {error ? (
            <div className="help-chat__state help-chat__state--error" role="alert">
              <strong>Help is unavailable</strong>
              <p>{error}</p>
              <button type="button" className="text-button" onClick={retry} disabled={!lastQuestion}>Retry</button>
            </div>
          ) : null}
          {result?.status === "insufficient_evidence" ? (
            <div className="help-chat__state" role="status"><strong>Insufficient documentation</strong><p>No reviewed passage supports that question yet.</p></div>
          ) : null}
          {result?.status === "unavailable" ? (
            <div className="help-chat__state help-chat__state--error" role="status"><strong>No answer returned</strong><p>The help model did not return a safe final answer. Nothing was inferred or replayed.</p><button type="button" className="text-button" onClick={retry}>Retry</button></div>
          ) : null}
          {result?.status === "answered" && result.answer ? (
            <div className="help-chat__answer" role="status">
              <span className="help-chat__label">Answer</span>
              <p>{result.answer}</p>
              <span className="help-chat__label">Reviewed sources</span>
              <ul>
                {result.sources.map((source) => {
                  const href = safeSourceHref(source.path);
                  return <li key={source.source_id}>{href ? <a href={href}>{source.title}</a> : <span>{source.title}</span>}</li>;
                })}
              </ul>
              <small>Profile: {result.model_profile} · {result.model_revision}</small>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function safeSourceHref(path: string): string | null {
  if (!/^(docs|specs)\/[a-zA-Z0-9._/-]+\.md$/.test(path) || path.includes("..")) return null;
  return `/${path}`;
}
