import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        panel: "rgb(255 255 255 / 0.05)",
        stroke: "rgb(255 255 255 / 0.10)",
      },
      backgroundImage: {
        "accent-gradient":
          "linear-gradient(135deg, rgb(34 211 238) 0%, rgb(139 92 246) 100%)",
        "radial-dark":
          "radial-gradient(ellipse at top, rgb(30 41 59 / 0.6) 0%, rgb(2 6 23) 55%, #000 100%)",
      },
      boxShadow: {
        glass: "0 1px 0 0 rgb(255 255 255 / 0.06) inset, 0 20px 40px -20px rgb(0 0 0 / 0.6)",
      },
      borderRadius: {
        "2xl": "1rem",
      },
    },
  },
  plugins: [],
};

export default config;
