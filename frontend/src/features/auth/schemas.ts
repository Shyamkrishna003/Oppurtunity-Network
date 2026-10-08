import { z } from "zod";

export const email = z
  .string()
  .trim()
  .min(1, "Enter your email address.")
  .email("Enter a valid email address.");

// The server applies the full strength rules; this catches the obvious case early.
export const newPassword = z
  .string()
  .min(10, "Use at least 10 characters.")
  .max(128, "Use at most 128 characters.");

export const loginSchema = z.object({
  email,
  password: z.string().min(1, "Enter your password."),
});
export type LoginValues = z.infer<typeof loginSchema>;

export const registerSchema = z.object({
  display_name: z.string().trim().min(1, "Enter your name.").max(80, "Use at most 80 characters."),
  email,
  password: newPassword,
});
export type RegisterValues = z.infer<typeof registerSchema>;

export const emailSchema = z.object({ email });
export type EmailValues = z.infer<typeof emailSchema>;

export const resetSchema = z
  .object({ new_password: newPassword, confirm: z.string() })
  .refine((values) => values.new_password === values.confirm, {
    path: ["confirm"],
    message: "The passwords do not match.",
  });
export type ResetValues = z.infer<typeof resetSchema>;

export const changePasswordSchema = z
  .object({
    current_password: z.string().min(1, "Enter your current password."),
    new_password: newPassword,
    confirm: z.string(),
  })
  .refine((values) => values.new_password === values.confirm, {
    path: ["confirm"],
    message: "The passwords do not match.",
  });
export type ChangePasswordValues = z.infer<typeof changePasswordSchema>;
