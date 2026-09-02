export const workspaceSections = [
  "overview",
  "inventory",
  "sales",
  "documents",
  "insights",
  "copilot",
  "administration",
  "guide",
] as const;

export type WorkspaceSection = (typeof workspaceSections)[number];

export function isWorkspaceSection(value: string): value is WorkspaceSection {
  return workspaceSections.includes(value as WorkspaceSection);
}
