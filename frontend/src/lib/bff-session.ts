import { createCipheriv, createDecipheriv, createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

import { cookies } from "next/headers";
import { createClient, type RedisClientType } from "redis";

const SESSION_COOKIE = "nexora_bff";
const REFRESH_COOKIE = "nexora_rt";
export const CSRF_COOKIE = "nexora_csrf";
const SESSION_SECONDS = 60 * 60 * 24 * 30;

type Session = { accessToken: string; refreshToken: string };

let redis: RedisClientType | undefined;

function secret(): string {
  const value = process.env.BFF_SESSION_SECRET;
  if (!value || value.length < 32) throw new Error("BFF_SESSION_SECRET must contain 32 characters");
  return value;
}

function sign(id: string): string {
  return createHmac("sha256", secret()).update(id).digest("base64url");
}

function encryptionKey(): Buffer {
  return createHash("sha256").update(secret()).digest();
}

function encrypt(session: Session): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", encryptionKey(), iv);
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify(session), "utf8"), cipher.final()]);
  return [iv, cipher.getAuthTag(), ciphertext].map((value) => value.toString("base64url")).join(".");
}

function decrypt(value: string): Session | null {
  try {
    const [iv, tag, ciphertext] = value.split(".").map((part) => Buffer.from(part, "base64url"));
    if (!iv || !tag || !ciphertext) return null;
    const decipher = createDecipheriv("aes-256-gcm", encryptionKey(), iv);
    decipher.setAuthTag(tag);
    return JSON.parse(Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString("utf8")) as Session;
  } catch {
    return null;
  }
}

async function client(): Promise<RedisClientType> {
  if (!redis) redis = createClient({ url: process.env.BFF_REDIS_URL ?? "redis://localhost:6379/3" });
  if (!redis.isOpen) await redis.connect();
  return redis;
}

function validSignedId(value: string | undefined): string | null {
  if (!value) return null;
  const [id, signature] = value.split(".");
  if (!id || !signature) return null;
  const expected = Buffer.from(sign(id));
  const supplied = Buffer.from(signature);
  return expected.length === supplied.length && timingSafeEqual(expected, supplied) ? id : null;
}

export async function readSession(): Promise<{ id: string; session: Session } | null> {
  const jar = await cookies();
  const id = validSignedId(jar.get(SESSION_COOKIE)?.value);
  if (!id) return null;
  const raw = await (await client()).get(`bff:session:${id}`);
  const session = raw ? decrypt(raw) : null;
  return session ? { id, session } : null;
}

export async function writeSession(accessToken: string, refreshToken: string): Promise<void> {
  const jar = await cookies();
  const current = validSignedId(jar.get(SESSION_COOKIE)?.value);
  const id = current ?? randomBytes(32).toString("base64url");
  await (await client()).set(`bff:session:${id}`, encrypt({ accessToken, refreshToken }), {
    EX: SESSION_SECONDS,
  });
  const secure = process.env.NODE_ENV === "production";
  jar.set(SESSION_COOKIE, `${id}.${sign(id)}`, { httpOnly: true, sameSite: "lax", secure, path: "/", maxAge: SESSION_SECONDS });
  if (!jar.get(CSRF_COOKIE)) jar.set(CSRF_COOKIE, randomBytes(24).toString("base64url"), { httpOnly: false, sameSite: "lax", secure, path: "/" });
}

export async function clearSession(): Promise<void> {
  const jar = await cookies();
  const id = validSignedId(jar.get(SESSION_COOKIE)?.value);
  if (id) await (await client()).del(`bff:session:${id}`);
  jar.delete(SESSION_COOKIE);
  jar.delete(REFRESH_COOKIE);
  jar.delete(CSRF_COOKIE);
}

export async function requireCsrf(request: Request): Promise<boolean> {
  const value = (await cookies()).get(CSRF_COOKIE)?.value;
  return Boolean(value && request.headers.get("X-CSRF-Token") === value);
}
