import { Megaphone } from "lucide-react";
import { EmptyState } from "@/components/common/EmptyState";

export default function BroadcastsPage() {
  return (
    <EmptyState
      icon={Megaphone}
      title="Broadcasts are coming soon"
      description="Use Chat to send a multi-channel broadcast (email + WhatsApp) right now. A dedicated composer will follow."
    />
  );
}
