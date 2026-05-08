import { Review, ReviewComment, ReviewDetail } from "../api/reviews";
import { LLMSettings, LLMProvider } from "../api/settings";
import { ScanResult, ScanFinding } from "../api/scan";

function randomId(): number {
  return Math.floor(Math.random() * 10000) + 1;
}

function randomDate(): string {
  const date = new Date();
  date.setDate(date.getDate() - Math.floor(Math.random() * 30));
  return date.toISOString();
}

export function createMockReview(overrides?: Partial<Review>): Review {
  return {
    id: randomId(),
    repository: 1,
    pr_number: Math.floor(Math.random() * 100) + 1,
    pr_title: "Add new feature to improve performance",
    head_sha: "abc123" + randomId(),
    status: "completed",
    risk_score: Math.floor(Math.random() * 100),
    summary: "Found 2 warnings, 1 error",
    created_at: randomDate(),
    completed_at: randomDate(),
    ...overrides,
  };
}

export function createMockComment(overrides?: Partial<ReviewComment>): ReviewComment {
  const categories = ["security", "code_quality", "best_practices", "performance"];
  const severities: ReviewComment["severity"][] = ["info", "warning", "error", "critical"];

  return {
    id: randomId(),
    file_path: `src/${["utils", "main", "config", "handler"][Math.floor(Math.random() * 4)]}.ts`,
    line_number: Math.floor(Math.random() * 100) + 1,
    category: categories[Math.floor(Math.random() * categories.length)],
    severity: severities[Math.floor(Math.random() * severities.length)],
    body: "Consider using a more efficient algorithm here.",
    suggested_fix: "Use memoization to cache results.",
    ...overrides,
  };
}

export function createMockReviewDetail(overrides?: Partial<ReviewDetail>): ReviewDetail {
  const comments = Array.from({ length: Math.floor(Math.random() * 5) + 1 }, () =>
    createMockComment()
  );
  return {
    ...createMockReview({ status: "completed" }),
    comments,
    ...overrides,
  };
}

export function createMockScanFinding(overrides?: Partial<ScanFinding>): ScanFinding {
  const categories = ["security", "code_quality", "best_practices"];
  const severities: ScanFinding["severity"][] = ["info", "warning", "error", "critical"];

  return {
    id: randomId(),
    category: categories[Math.floor(Math.random() * categories.length)],
    severity: severities[Math.floor(Math.random() * severities.length)],
    file_path: `src/${["utils", "main", "config"][Math.floor(Math.random() * 3)]}.ts`,
    line_number: Math.floor(Math.random() * 100) + 1,
    message: "Potential issue detected in this file",
    rule_id: "SEC-001",
    ...overrides,
  };
}

export function createMockScanResult(overrides?: Partial<ScanResult>): ScanResult {
  const findings = Array.from({ length: Math.floor(Math.random() * 10) + 1 }, () =>
    createMockScanFinding()
  );

  return {
    id: randomId(),
    repository: 1,
    scan_id: "scan-" + randomId(),
    status: "completed",
    summary: `Found ${findings.length} issues`,
    health_score: Math.floor(Math.random() * 40) + 60,
    findings,
    started_at: randomDate(),
    completed_at: randomDate(),
    ...overrides,
  };
}

export function createMockLLMProvider(overrides?: Partial<LLMProvider>): LLMProvider {
  const providers = ["openai", "anthropic", "google", "azure"];
  const models = ["gpt-4", "claude-3", "gemini-pro", "gpt-4-turbo"];

  return {
    id: randomId(),
    name: "My " + providers[Math.floor(Math.random() * providers.length)] + " Key",
    provider_type: providers[Math.floor(Math.random() * providers.length)],
    api_key: "sk-..." + randomId(),
    model_name: models[Math.floor(Math.random() * models.length)],
    is_active: true,
    is_default: Math.random() > 0.7,
    ...overrides,
  };
}

export function createMockLLMSettings(): LLMSettings {
  const providers = Array.from({ length: Math.floor(Math.random() * 3) + 1 }, () =>
    createMockLLMProvider()
  );
  const defaultProvider = providers.find((p) => p.is_default) || providers[0];

  return {
    providers,
    default_provider: defaultProvider?.id || null,
  };
}

export const MOCK_REVIEWS = Array.from({ length: 15 }, () => createMockReview());

export const MOCK_SCAN = createMockScanResult();

export const MOCK_LLM_SETTINGS = createMockLLMSettings();
