// Unit tests (Jest + React Testing Library). End-to-end tests live in e2e/ (Playwright).
import nextJest from "next/jest.js";

const createJestConfig = nextJest({ dir: "./" });

/** @type {import('jest').Config} */
const config = {
  testEnvironment: "jsdom",
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  testPathIgnorePatterns: ["<rootDir>/node_modules/", "<rootDir>/e2e/", "<rootDir>/.next/"],
  moduleNameMapper: { "^@/(.*)$": "<rootDir>/$1" },
};

export default createJestConfig(config);
