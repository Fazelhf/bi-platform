/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{vue,ts}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Vazirmatn", "Tahoma", "system-ui", "sans-serif"],
      },
      colors: {
        brand: {
          50: "#eef4ff",
          500: "#3b6fed",
          600: "#2b57d4",
          700: "#2244ab",
        },
        // Design tokens taken from the reference mockup.
        ink: {
          DEFAULT: "#1c1c1e", // near-black active / dark cards
          soft: "#2a2a2d",
        },
        canvas: "#e9e8e4", // warm light-gray page background
        accent: {
          50: "#e7f8ef",
          500: "#10b981", // green — online, success, primary actions
          600: "#059669",
        },
      },
      borderRadius: {
        card: "1.5rem", // 24px — the mockup's card radius
      },
      boxShadow: {
        soft: "0 6px 24px -8px rgba(20,20,25,0.10)",
        pop: "0 12px 40px -8px rgba(20,20,25,0.28)",
      },
    },
  },
  plugins: [],
};
