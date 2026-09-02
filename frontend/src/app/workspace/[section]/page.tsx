import { redirect } from "next/navigation";

import { WorkspaceShell } from "@/components/workspace-shell";
import { readSession } from "@/lib/bff-session";
import { isWorkspaceSection } from "@/lib/workspace-sections";

export default async function WorkspaceSectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  if (!(await readSession())) redirect("/login");
  const { section } = await params;
  if (!isWorkspaceSection(section)) redirect("/workspace/overview");
  return <WorkspaceShell section={section} />;
}
