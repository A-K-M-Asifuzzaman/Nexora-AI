import { Sparkles } from "lucide-react";

export function Brand() {
  return (
    <div className="brand" role="img" aria-label="Nexora AI">
      <span className="brand-mark"><Sparkles size={19} strokeWidth={2.2} /></span>
      <span>Nexora <em>AI</em></span>
    </div>
  );
}
