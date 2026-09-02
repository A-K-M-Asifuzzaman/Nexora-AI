import { redirect } from "next/navigation";

import { readSession } from "@/lib/bff-session";

export default async function WorkspacePage() {
  if (!(await readSession())) redirect("/login");
  redirect("/workspace/overview");
}
