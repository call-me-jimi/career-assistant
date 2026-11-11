import { useEffect, useState } from "react";
import { API_BASE } from "./ws";

/* Quick-reply labels are drawn here, so the WebSocket's translation of chat
   messages never reaches them. The backend's translator is cached per string;
   this cache only saves the round trip within one page load. */
const cache = new Map<string, string>();
const keyOf = (language: string, text: string) => `${language}\u0000${text}`;

function isEnglish(language: string): boolean {
  return ["", "english", "en"].includes(language.trim().toLowerCase());
}

export function useTranslate(texts: string[], language: string): (text: string) => string {
  const [, rerender] = useState(0);
  const english = isEnglish(language);
  const missing = english ? [] : texts.filter((t) => !cache.has(keyOf(language, t)));
  const missingKey = missing.join("\u0001");

  useEffect(() => {
    if (!missing.length) return;
    let live = true;
    fetch(`${API_BASE}/api/translate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language, texts: missing }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data) return;
        missing.forEach((t, i) => cache.set(keyOf(language, t), data.translations[i] ?? t));
        if (live) rerender((n) => n + 1);
      })
      .catch(() => {}); // the English label is a fine fallback
    return () => {
      live = false;
    };
    // `missingKey` stands in for `missing`, which is a new array every render.
  }, [language, missingKey]);

  return (text) => (english ? text : cache.get(keyOf(language, text)) ?? text);
}
