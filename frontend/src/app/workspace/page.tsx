import { redirect } from "next/navigation";

import { WorkspaceShell } from "@/components/workspace-shell";
import { readSession } from "@/lib/bff-session";

import "./workspace.css";

export default async function WorkspacePage() {
  if (!(await readSession())) redirect("/login");
  return <WorkspaceShell />;
}
