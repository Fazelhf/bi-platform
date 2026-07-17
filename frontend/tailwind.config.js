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
      },
    },
  },
  plugins: [],
};
