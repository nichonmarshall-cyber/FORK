// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Home from "./page";
import { EMPTY_NOTEBOOK, FULL_NOTEBOOK, STUDENT } from "@/lib/notebook.fixtures";
import { ApiError } from "@/lib/types";

vi.mock("@/lib/notebook", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/notebook")>();
  return { ...actual, getNotebook: vi.fn(), register: vi.fn(), login: vi.fn(), logout: vi.fn() };
});

import { NotSignedIn, getNotebook, login, logout, register } from "@/lib/notebook";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Home", () => {
  it("signed out: explains Fork, offers sign-in, and keeps compare open to everyone", async () => {
    vi.mocked(getNotebook).mockRejectedValue(new NotSignedIn());
    render(<Home />);
    expect(await screen.findByRole("tab", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /compare majors without an account/i })).toHaveAttribute(
      "href",
      "/compare",
    );
  });

  it("signed in: opens the notebook", async () => {
    vi.mocked(getNotebook).mockResolvedValue(FULL_NOTEBOOK);
    render(<Home />);
    expect(await screen.findByRole("heading", { name: "Sam's notebook" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Notebook" })).toHaveAttribute("aria-current", "page");
  });

  it("creating an account loads the new, empty notebook", async () => {
    vi.mocked(getNotebook)
      .mockRejectedValueOnce(new NotSignedIn())
      .mockResolvedValueOnce(EMPTY_NOTEBOOK);
    vi.mocked(register).mockResolvedValue(STUDENT);
    render(<Home />);

    fireEvent.click(await screen.findByRole("tab", { name: "Create account" }));
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "sam@example.edu" } });
    fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: "short" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my notebook" }));
    // Too short: caught before any request.
    expect(screen.getByRole("alert")).toHaveTextContent("at least 10");
    expect(register).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: "long enough pass" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my notebook" }));
    expect(await screen.findByRole("heading", { name: /your notebook is empty/i })).toBeInTheDocument();
    expect(register).toHaveBeenCalledWith("sam@example.edu", "long enough pass", "");
  });

  it("shows the backend's sign-in error and stays on the form", async () => {
    vi.mocked(getNotebook).mockRejectedValue(new NotSignedIn());
    vi.mocked(login).mockRejectedValue(new ApiError("That email and password don't match an account."));
    render(<Home />);
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "a@b.edu" } });
    fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: "whatever123" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("don't match an account");
  });

  it("signing out returns to the welcome screen", async () => {
    vi.mocked(getNotebook).mockResolvedValue(FULL_NOTEBOOK);
    vi.mocked(logout).mockResolvedValue({ status: "signed_out" });
    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Sign in" })).toBeInTheDocument());
  });
});
