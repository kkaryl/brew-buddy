import { X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type JSX } from "react";
import type { ContactResponse, CreateContactRequest } from "../api/types";
import {
  errorToFeedbackNotice,
  validateContactForm,
  type ContactFieldErrors,
  type FeedbackNotice,
} from "./formatters";
import { StatusBanner } from "./StatusFeedback";
import { FormField, PillButton, PrimaryButton } from "./ui";

export interface ContactFormModalProps {
  readonly isOpen: boolean;
  readonly onClose: () => void;
  readonly onCreateContact: (payload: CreateContactRequest) => Promise<ContactResponse>;
}

export function ContactFormModal({
  isOpen,
  onClose,
  onCreateContact,
}: ContactFormModalProps): JSX.Element | null {
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [role, setRole] = useState("");
  const [organization, setOrganization] = useState("");
  const [contextNotes, setContextNotes] = useState("");
  const [fieldErrors, setFieldErrors] = useState<ContactFieldErrors>({});
  const [apiNotice, setApiNotice] = useState<FeedbackNotice | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const nameInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    nameInputRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape" && !submitting) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose, submitting]);

  if (!isOpen) {
    return null;
  }

  const resetForm = (): void => {
    setName("");
    setTitle("");
    setRole("");
    setOrganization("");
    setContextNotes("");
    setFieldErrors({});
    setApiNotice(null);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setApiNotice(null);

    const validationErrors = validateContactForm({
      name,
      title,
      role,
      organization,
      contextNotes,
    });
    setFieldErrors(validationErrors);
    if (Object.keys(validationErrors).length > 0) {
      return;
    }

    setSubmitting(true);
    try {
      const payload: CreateContactRequest = {
        name: name.trim(),
        title: title.trim() || null,
        role: role.trim() || null,
        organization: organization.trim() || null,
        context_notes: contextNotes.trim() || null,
      };
      await onCreateContact(payload);
      resetForm();
      onClose();
    } catch (err: unknown) {
      setApiNotice(errorToFeedbackNotice(err, "Could not save counterpart"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-brew-plum/35 p-0 backdrop-blur-xs sm:items-center sm:p-5"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) {
          onClose();
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-new-contact-title"
        className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-[32px] border border-brew-border bg-brew-paper p-6 shadow-floating sm:rounded-[30px] sm:p-7"
      >
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="brew-eyebrow">NEW CONNECTION</p>
            <h2 id="modal-new-contact-title" className="brew-section-heading mt-0.5">
              New Counterpart
            </h2>
          </div>
          <PillButton
            id="btn-close-contact-modal"
            variant="ghost"
            size="sm"
            disabled={submitting}
            onClick={onClose}
            aria-label="Close New Counterpart dialog"
          >
            <X className="h-4 w-4" aria-hidden="true" />
            <span>Close</span>
          </PillButton>
        </div>

        <form onSubmit={(e) => void handleSubmit(e)} noValidate className="mt-5 space-y-4">
          {apiNotice && <StatusBanner notice={apiNotice} />}

          <FormField
            htmlFor="contact-name-input"
            label="Full name"
            required
            error={fieldErrors.name}
            errorId="contact-name-error"
          >
            <input
              ref={nameInputRef}
              id="contact-name-input"
              name="name"
              type="text"
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
              aria-invalid={fieldErrors.name ? "true" : "false"}
              aria-describedby={fieldErrors.name ? "contact-name-error" : undefined}
              placeholder="e.g., Alex Morgan"
              className="brew-field-control"
            />
          </FormField>

          <div className="grid gap-4 sm:grid-cols-2">
            <FormField
              htmlFor="contact-title-input"
              label="Title"
              error={fieldErrors.title}
            >
              <input
                id="contact-title-input"
                name="title"
                type="text"
                maxLength={120}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                aria-invalid={fieldErrors.title ? "true" : "false"}
                placeholder="e.g., Staff ML Engineer"
                className="brew-field-control"
              />
            </FormField>

            <FormField
              htmlFor="contact-organization-input"
              label="Organization"
              error={fieldErrors.organization}
            >
              <input
                id="contact-organization-input"
                name="organization"
                type="text"
                maxLength={160}
                value={organization}
                onChange={(e) => setOrganization(e.target.value)}
                aria-invalid={fieldErrors.organization ? "true" : "false"}
                placeholder="e.g., Northstar Systems"
                className="brew-field-control"
              />
            </FormField>
          </div>

          <FormField
            htmlFor="contact-role-input"
            label="Relationship role"
            error={fieldErrors.role}
          >
            <input
              id="contact-role-input"
              name="role"
              type="text"
              maxLength={120}
              value={role}
              onChange={(e) => setRole(e.target.value)}
              aria-invalid={fieldErrors.role ? "true" : "false"}
              placeholder="e.g., Engineering Mentor, Industry Peer"
              className="brew-field-control"
            />
          </FormField>

          <FormField
            htmlFor="contact-notes-input"
            label="Background context"
            error={fieldErrors.context_notes}
            errorId="contact-notes-error"
          >
            <textarea
              id="contact-notes-input"
              name="context_notes"
              rows={3}
              maxLength={2000}
              value={contextNotes}
              onChange={(e) => setContextNotes(e.target.value)}
              aria-invalid={fieldErrors.context_notes ? "true" : "false"}
              aria-describedby={fieldErrors.context_notes ? "contact-notes-error" : undefined}
              placeholder="How you connected or relevant team context you want grounded in prep."
              className="brew-field-control"
            />
          </FormField>

          <div className="flex flex-col-reverse justify-end gap-2.5 pt-2 sm:flex-row">
            <PillButton variant="outline" disabled={submitting} onClick={onClose}>
              Cancel
            </PillButton>
            <PrimaryButton
              id="btn-submit-create-contact"
              type="submit"
              loading={submitting}
            >
              {submitting ? "Saving..." : "Save Counterpart"}
            </PrimaryButton>
          </div>
        </form>
      </div>
    </div>
  );
}
