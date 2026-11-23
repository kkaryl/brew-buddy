import { useEffect, useRef, useState, type FormEvent, type JSX } from "react";
import type { ContactResponse, CreateContactRequest } from "../api/types";
import {
  errorToFeedbackNotice,
  validateContactForm,
  type ContactFieldErrors,
  type FeedbackNotice,
} from "./formatters";
import { StatusBanner } from "./StatusFeedback";

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
      className="fixed inset-0 z-50 flex items-end justify-center bg-[#23170F]/45 p-0 sm:items-center sm:p-4"
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
        className="md-card-elevated max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-3xl rounded-b-none p-6 sm:rounded-3xl sm:p-7"
      >
        <div className="flex items-center justify-between gap-3">
          <h2 id="modal-new-contact-title" className="text-xl font-semibold text-[#23170F]">
            New Counterpart
          </h2>
          <button
            id="btn-close-contact-modal"
            type="button"
            disabled={submitting}
            onClick={onClose}
            className="md-btn md-btn-text min-h-9 px-3 py-1 text-xs"
          >
            Cancel
          </button>
        </div>

        <form onSubmit={(e) => void handleSubmit(e)} noValidate className="mt-5 space-y-4">
          {apiNotice && <StatusBanner notice={apiNotice} />}

          <div>
            <label htmlFor="contact-name-input" className="block text-sm font-medium text-[#23170F]">
              Full name <span className="text-[#9E2A2B]">*</span>
            </label>
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
              className="md-input mt-1.5"
            />
            {fieldErrors.name && (
              <p id="contact-name-error" role="alert" className="mt-1 text-xs text-[#9E2A2B]">
                {fieldErrors.name}
              </p>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label
                htmlFor="contact-title-input"
                className="block text-sm font-medium text-[#23170F]"
              >
                Title
              </label>
              <input
                id="contact-title-input"
                name="title"
                type="text"
                maxLength={120}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                aria-invalid={fieldErrors.title ? "true" : "false"}
                placeholder="e.g., Staff ML Engineer"
                className="md-input mt-1.5"
              />
              {fieldErrors.title && (
                <p role="alert" className="mt-1 text-xs text-[#9E2A2B]">
                  {fieldErrors.title}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="contact-organization-input"
                className="block text-sm font-medium text-[#23170F]"
              >
                Organization
              </label>
              <input
                id="contact-organization-input"
                name="organization"
                type="text"
                maxLength={160}
                value={organization}
                onChange={(e) => setOrganization(e.target.value)}
                aria-invalid={fieldErrors.organization ? "true" : "false"}
                placeholder="e.g., Northstar Systems"
                className="md-input mt-1.5"
              />
              {fieldErrors.organization && (
                <p role="alert" className="mt-1 text-xs text-[#9E2A2B]">
                  {fieldErrors.organization}
                </p>
              )}
            </div>
          </div>

          <div>
            <label htmlFor="contact-role-input" className="block text-sm font-medium text-[#23170F]">
              Relationship role
            </label>
            <input
              id="contact-role-input"
              name="role"
              type="text"
              maxLength={120}
              value={role}
              onChange={(e) => setRole(e.target.value)}
              aria-invalid={fieldErrors.role ? "true" : "false"}
              placeholder="e.g., Engineering Mentor, Prospective Customer"
              className="md-input mt-1.5"
            />
            {fieldErrors.role && (
              <p role="alert" className="mt-1 text-xs text-[#9E2A2B]">
                {fieldErrors.role}
              </p>
            )}
          </div>

          <div>
            <label
              htmlFor="contact-notes-input"
              className="block text-sm font-medium text-[#23170F]"
            >
              Background context
            </label>
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
              className="md-textarea mt-1.5"
            />
            {fieldErrors.context_notes && (
              <p id="contact-notes-error" role="alert" className="mt-1 text-xs text-[#9E2A2B]">
                {fieldErrors.context_notes}
              </p>
            )}
          </div>

          <div className="flex flex-col-reverse justify-end gap-2.5 pt-2 sm:flex-row">
            <button
              type="button"
              disabled={submitting}
              onClick={onClose}
              className="md-btn md-btn-outlined"
            >
              Cancel
            </button>
            <button
              id="btn-submit-create-contact"
              type="submit"
              disabled={submitting}
              className="md-btn md-btn-filled"
            >
              {submitting ? "Saving..." : "Save Counterpart"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
