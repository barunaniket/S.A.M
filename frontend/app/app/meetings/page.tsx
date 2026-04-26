import { Calendar } from "lucide-react";
import { EmptyState } from "@/components/common/EmptyState";

export default function MeetingsPage() {
  return (
    <EmptyState
      icon={Calendar}
      title="Meetings view is coming soon"
      description="For now, manage meetings from Chat — S.A.M will create, reschedule, and cancel them on your Google Calendar."
    />
  );
}
