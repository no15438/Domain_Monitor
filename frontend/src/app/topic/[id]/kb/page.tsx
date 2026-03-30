import { redirect } from "next/navigation";

// Legacy alias: the topic page is now the single knowledge workspace.
export default async function TopicWorkspaceAliasPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(`/topic/${id}`);
}
