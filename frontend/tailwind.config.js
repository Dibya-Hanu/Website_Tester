export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        forest: "#163c34",
        mint: "#e7f1eb",
        ink: "#243a34",
        muted: "#7b8782",
        paper: "#f7f8f6",
      },
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"] },
    },
  },
  plugins: [],
};
