import { AgendaStrip } from "@/components/shell/AgendaStrip";
import { ChatPanel } from "@/components/chat/ChatPanel";

export default function ChatHomePage() {
  return (
    <div className="flex h-full flex-col">
      <AgendaStrip />
      <div className="flex-1 overflow-hidden">
        <ChatPanel />
      </div>
    </div>
  );
}
