import { UserSquare2 } from "lucide-react";
import { EmptyState } from "@/components/common/EmptyState";

export default function FacultyPage() {
  return (
    <EmptyState
      icon={UserSquare2}
      title="Faculty roster is coming soon"
      description="Upload faculty rosters via the API today (POST /api/v1/uploads). A managed view will land here next."
    />
  );
}
