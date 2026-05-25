"use client";

import { useState } from "react";

export default function RecordInterviewHelp() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-xs text-accent hover:underline"
      >
        How to record →
      </button>
      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="max-w-3xl w-full max-h-[85vh] overflow-y-auto bg-panel border border-border rounded-2xl p-6 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between items-center">
              <h2 className="text-xl font-semibold">
                Recording an interview on Ubuntu
              </h2>
              <button
                onClick={() => setOpen(false)}
                className="text-subtle hover:text-text"
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <section className="space-y-2 text-sm leading-relaxed">
              <h3 className="font-semibold text-base">Zoom (Linux client)</h3>
              <p>
                Built-in <code className="text-accent">Record</code> button in
                the meeting controls saves an <code>.m4a</code> +{" "}
                <code>.mp4</code> to <code>~/Documents/Zoom/</code>. Free tier
                works for the meeting host; participants need the host&apos;s
                permission.
              </p>
            </section>

            <section className="space-y-2 text-sm leading-relaxed">
              <h3 className="font-semibold text-base">Google Meet</h3>
              <p>
                No native recording on free accounts. Use OBS or{" "}
                <code>ffmpeg</code> below.
              </p>
            </section>

            <section className="space-y-2 text-sm leading-relaxed">
              <h3 className="font-semibold text-base">Microsoft Teams</h3>
              <p>
                Cloud recording is paid-only. On Linux use OBS or{" "}
                <code>ffmpeg</code>.
              </p>
            </section>

            <section className="space-y-2 text-sm leading-relaxed">
              <h3 className="font-semibold text-base">OBS Studio (universal)</h3>
              <ol className="list-decimal list-inside space-y-1">
                <li>
                  Install: <code>sudo apt install obs-studio</code> (or
                  Flatpak).
                </li>
                <li>
                  Add two audio sources: <em>Audio Input Capture</em>{" "}
                  (microphone) and <em>Audio Output Capture</em> (PulseAudio
                  &quot;Monitor of …&quot;).
                </li>
                <li>Record (MKV is the default container).</li>
                <li>
                  Extract audio:{" "}
                  <code>ffmpeg -i record.mkv -vn -acodec copy out.m4a</code>
                </li>
              </ol>
            </section>

            <section className="space-y-2 text-sm leading-relaxed">
              <h3 className="font-semibold text-base">
                One-liner with <code>ffmpeg</code> (PulseAudio)
              </h3>
              <p>
                Find your output sink with{" "}
                <code>pactl list short sinks</code>, then:
              </p>
              <pre className="bg-bg/50 p-3 rounded-lg text-xs overflow-x-auto border border-border">
                {`ffmpeg -f pulse -i default \\
       -f pulse -i alsa_output.<SINK>.monitor \\
       -filter_complex amix=inputs=2 -ac 1 -ar 16000 \\
       interview.mp3`}
              </pre>
              <p className="text-subtle">
                Mixes microphone + system audio into a single mono file.
              </p>
            </section>

            <section className="space-y-2 text-sm leading-relaxed">
              <h3 className="font-semibold text-base text-warn">
                Consent
              </h3>
              <p className="text-subtle">
                Recording laws vary by jurisdiction. In many places you need
                the other participant&apos;s consent — check before
                recording.
              </p>
            </section>
          </div>
        </div>
      )}
    </>
  );
}
