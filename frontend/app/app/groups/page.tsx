import { Users } from "lucide-react";
import { EmptyState } from "@/components/common/EmptyState";

export default function GroupsPage() {
  return (
    <EmptyState
      icon={Users}
      title="Groups are coming soon"
      description="Create faculty groups via Chat (“create group CSE-Year-2 with…”). A dedicated UI for membership management will arrive next."
    />
  );
}
