import { useState } from "react";

import { StreamedAnswer } from "../components/Answer";
import { useApp } from "../state";

export function Ask() {
  const { client } = useApp();
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);

  return (
    <section aria-labelledby="ask-title" className="stack">
      <h1 id="ask-title">Ask about hardening</h1>
      <p>
        Answers come only from HardenGarden&apos;s knowledge base and always list their sources. If
        the knowledge base does not cover a question, you get a plain &quot;not enough
        information&quot;.
      </p>
      <form
        className="field"
        onSubmit={(e) => {
          e.preventDefault();
          if (question.trim()) setAsked(question.trim());
        }}
      >
        <label htmlFor="question">Your question</label>
        <textarea
          id="question"
          rows={3}
          maxLength={500}
          value={question}
          onChange={(e) => {
            setQuestion(e.target.value);
          }}
        />
        <div>
          <button className="button quiet" type="submit" disabled={!question.trim()}>
            Use this question
          </button>
        </div>
      </form>
      {asked && (
        <div className="panel">
          <h2>{asked}</h2>
          <StreamedAnswer
            key={asked}
            label="Ask"
            start={(onEvent, signal) => client.chat(asked, onEvent, signal)}
          />
        </div>
      )}
    </section>
  );
}
