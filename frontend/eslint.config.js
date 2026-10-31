import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config({ ignores: ["dist", "coverage"] }, js.configs.recommended, {
  files: ["src/**/*.{ts,tsx}", "vite.config.ts"],
  extends: [tseslint.configs.strictTypeChecked, tseslint.configs.stylisticTypeChecked],
  languageOptions: {
    globals: globals.browser,
    parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
  },
  plugins: { "react-hooks": reactHooks },
  rules: reactHooks.configs.recommended.rules,
});
