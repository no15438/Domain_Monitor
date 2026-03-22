import { redirect } from "next/navigation";

export default function KBRedirectPage({ params }: { params: { id: string } }) {
  redirect(`/topic/${params.id}`);
}
