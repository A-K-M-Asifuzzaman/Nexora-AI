/**
 * Single-flight refresh lock (finding P1-33).
 *
 * Refresh tokens rotate with reuse detection, so two parallel requests that both
 * refresh will revoke the session family and log the user out. Proven against
 * the real backend: concurrent refreshes returned `[200, REFRESH_REUSE_DETECTED]`
 * and the session was dead afterwards.
 *
 * These pin the lock primitive that prevents it. They use the real Redis the app
 * uses — a mocked lock would prove only that the mock is exclusive.
 */

import { afterAll, describe, expect, it } from "vitest";

import { acquireRefreshLock, closeSessionStore, releaseRefreshLock } from "./bff-session";

const sessionId = () => `test-${Math.random().toString(36).slice(2, 12)}`;

describe("refresh single-flight lock", () => {
  afterAll(async () => {
    await closeSessionStore();
  });

  it("grants the lock to exactly one of two concurrent callers", async () => {
    const id = sessionId();
    const [first, second] = await Promise.all([
      acquireRefreshLock(id),
      acquireRefreshLock(id),
    ]);
    const owners = [first, second].filter((owner): owner is string => owner !== null);
    expect(owners).toHaveLength(1);
    await releaseRefreshLock(id, owners[0]);
  });

  it("grants the lock again once released", async () => {
    const id = sessionId();
    const first = await acquireRefreshLock(id);
    expect(first).not.toBeNull();
    await releaseRefreshLock(id, first!);
    const second = await acquireRefreshLock(id);
    expect(second).not.toBeNull();
    await releaseRefreshLock(id, second!);
  });

  it("does not let one session block another", async () => {
    const a = sessionId();
    const b = sessionId();
    const ownerA = await acquireRefreshLock(a);
    const ownerB = await acquireRefreshLock(b);
    expect(ownerA).not.toBeNull();
    expect(ownerB).not.toBeNull();
    await Promise.all([releaseRefreshLock(a, ownerA!), releaseRefreshLock(b, ownerB!)]);
  });

  it("holds the lock against a repeated attempt by the same session", async () => {
    const id = sessionId();
    const owner = await acquireRefreshLock(id);
    expect(owner).not.toBeNull();
    expect(await acquireRefreshLock(id)).toBeNull();
    await releaseRefreshLock(id, owner!);
  });

  it("does not release a lock owned by another caller", async () => {
    const id = sessionId();
    const owner = await acquireRefreshLock(id);
    expect(owner).not.toBeNull();
    await releaseRefreshLock(id, "not-the-owner");
    expect(await acquireRefreshLock(id)).toBeNull();
    await releaseRefreshLock(id, owner!);
  });
});
