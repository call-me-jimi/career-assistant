import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0d12",
        panel: "#141822",
        panel2: "#1b2030",
        border: "#242a3a",
        text: "#e6e8ee",
        subtle: "#8a93a8",
        accent: "#7aa2ff",
        ok: "#6ee7b7",
        warn: "#fcd34d",
        err: "#f87171",
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};

export default config;
