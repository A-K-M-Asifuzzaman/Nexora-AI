import { AuthFrame } from "../login/page";

export default function RegisterPage() {
  return <AuthFrame mode="register" title="Create your workspace" subtitle="Start with your account. Your organization comes next." switchText="Already have an account?" switchHref="/login" switchLabel="Sign in" />;
}
