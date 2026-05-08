import { http, HttpResponse } from "msw";
import {
  MOCK_REVIEWS,
  MOCK_LLM_SETTINGS,
  createMockReviewDetail,
  createMockScanResult,
} from "./data";

export const handlers = [
  // Reviews API
  http.get("/api/v1/reviews/", ({ request }) => {
    const url = new URL(request.url);
    const pageStr = url.searchParams.get("page");
    const pageSizeStr = url.searchParams.get("page_size");
    const page = pageStr ? parseInt(pageStr) : 1;
    const pageSize = pageSizeStr ? parseInt(pageSizeStr) : 10;

    const start = (page - 1) * pageSize;
    const end = start + pageSize;
    const results = MOCK_REVIEWS.slice(start, end);

    return HttpResponse.json({
      count: MOCK_REVIEWS.length,
      next: end < MOCK_REVIEWS.length ? `?page=${page + 1}` : null,
      previous: page > 1 ? `?page=${page - 1}` : null,
      results,
    });
  }),

  http.get("/api/v1/reviews/:id", ({ params }) => {
    const id = params.id ? parseInt(String(params.id)) : 1;
    const review = createMockReviewDetail({ id });
    return HttpResponse.json(review);
  }),

  http.post("/api/v1/reviews/", async ({ request }) => {
    const body = await request.json() as { repository: number; pr_number: number };
    const review = {
      id: Math.floor(Math.random() * 10000) + 1,
      ...body,
      status: "pending" as const,
      risk_score: 0,
      summary: "",
      created_at: new Date().toISOString(),
      completed_at: null,
    };
    return HttpResponse.json(review, { status: 201 });
  }),

  http.get("/api/v1/reviews/:id/comments/", ({ params }) => {
    const id = params.id ? parseInt(String(params.id)) : 1;
    const review = createMockReviewDetail({ id });
    return HttpResponse.json(review.comments);
  }),

  // Repositories API
  http.get("/api/v1/repositories/", () => {
    return HttpResponse.json({
      results: [
        {
          id: 1,
          full_name: "testuser/test-repo",
          name: "test-repo",
          is_active: true,
        },
      ],
    });
  }),

  http.post("/api/v1/repositories/:id/scan/", () => {
    return HttpResponse.json({
      scan_id: "scan-" + Math.floor(Math.random() * 10000),
    });
  }),

  http.get("/api/v1/repositories/:id/scans/latest/", () => {
    return HttpResponse.json(createMockScanResult());
  }),

  // Settings API
  http.get("/api/v1/settings/llm/", () => {
    return HttpResponse.json(MOCK_LLM_SETTINGS);
  }),

  http.post("/api/v1/settings/llm/", async ({ request }) => {
    const body = await request.json() as Record<string, unknown>;
    const provider = {
      id: Math.floor(Math.random() * 10000) + 1,
      ...body,
      is_active: true,
      is_default: false,
    };
    return HttpResponse.json(provider, { status: 201 });
  }),

  http.delete("/api/v1/settings/llm/:id/", () => {
    return HttpResponse.json({ success: true });
  }),

  http.post("/api/v1/settings/llm/:id/test/", () => {
    return HttpResponse.json({ success: true, message: "Connection successful" });
  }),

  http.post("/api/v1/settings/llm/:id/set_default/", ({ params }) => {
    const id = params.id ? parseInt(String(params.id)) : 1;
    return HttpResponse.json({ id, is_default: true });
  }),

  // Health check
  http.get("/health/", () => {
    return HttpResponse.json({ status: "ok", db: "ok", redis: "ok" });
  }),

  // Auth (fallback)
  http.post("/api/v1/auth/login/", async () => {
    return HttpResponse.json({
      access: "mock-token-" + Date.now(),
      refresh: "mock-refresh-" + Date.now(),
    });
  }),
];
