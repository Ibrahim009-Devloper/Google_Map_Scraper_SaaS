"""
Autonomous AI Google Maps Lead Generation Agent - Main CLI Runner.
Interactive entry point with Human-in-the-Loop review and Rich terminal styling.
"""

import sys
import os
import argparse
from typing import Optional

# Ensure standard output and error support UTF-8 on Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm

from agent.planner import generate_plan
from agent.pipeline import run_pipeline

# Expose ASGI FastAPI application so both `uvicorn main:app` and `uvicorn backend.main:app` work
from backend.main import app

console = Console(force_terminal=True)


def display_welcome_banner():
    banner_text = """[bold cyan]🗺️  Autonomous AI Google Maps Lead Generation Agent[/bold cyan]
[dim]Zero-Browser Reverse API (`tbm=map`) • Geo-Splitting • Multi-Threaded Website Enricher[/dim]"""
    console.print(Panel(banner_text, border_style="cyan", expand=False))


def display_plan_summary_human(plan):
    """
    Renders a simple, elegant, human-readable summary instead of complex JSON.
    Example:
      Website: No (Social Link Only)
      Email: No
      Locations: Banani, Dhanmondi, Uttara...
    """
    web_map = {
        "no_website": "❌ No Website Only (Includes Social Links)",
        "has_real_website": "✅ Own Website Required",
        "any": "🌐 Any (With or Without Website)",
    }
    web_text = web_map.get(plan.filters.website_requirement, plan.filters.website_requirement)

    # Sub-location names
    loc_names = [loc.area_name.split(",")[0].strip() for loc in plan.sub_locations]
    if len(loc_names) <= 6:
        loc_str = ", ".join(loc_names)
    else:
        loc_str = ", ".join(loc_names[:6]) + f" [dim](+{len(loc_names) - 6} more zones)[/dim]"

    rating_str = f"{plan.filters.min_rating}★" if plan.filters.max_rating is None else f"{plan.filters.min_rating}★ - {plan.filters.max_rating}★"
    reviews_str = f"{plan.filters.min_reviews}+" if plan.filters.max_reviews is None else f"{plan.filters.min_reviews} - {plan.filters.max_reviews}"

    summary_text = f"""[bold cyan]🎯 Target Keywords :[/bold cyan] [bold white]{', '.join(plan.keywords)}[/bold white]
[bold cyan]📍 Target Areas    :[/bold cyan] [bold green]{loc_str}[/bold green] ([dim]{len(plan.sub_locations)} micro-zones[/dim])
[bold cyan]🌐 Website Filter  :[/bold cyan] [bold yellow]{web_text}[/bold yellow]
[bold cyan]📞 Must Have Phone :[/bold cyan] {'[green]Yes[/green]' if plan.filters.must_have_phone else '[dim]No (Optional)[/dim]'}
[bold cyan]✉️  Extract Emails  :[/bold cyan] {'[green]Yes[/green]' if plan.enrichment.extract_emails else '[dim]No[/dim]'}
[bold cyan]🔗 Extract Socials :[/bold cyan] {'[green]Yes[/green]' if plan.enrichment.extract_socials else '[dim]No[/dim]'}
[bold cyan]⭐ Rating / Reviews :[/bold cyan] {rating_str} / {reviews_str} reviews
[bold cyan]📄 Search Depth    :[/bold cyan] Up to {plan.filters.max_pages_per_search * 20} leads per micro-zone"""

    console.print(Panel(summary_text, title="[bold yellow]📋 AI Search Plan Preview[/bold yellow]", border_style="cyan", expand=False))


def display_results_summary(result):
    leads = result["leads"]

    stats_table = Table(title="📊 Pipeline Execution Summary", border_style="green")
    stats_table.add_column("Metric", style="bold cyan")
    stats_table.add_column("Count", style="bold white")

    total_leads = len(leads)
    has_phone = sum(1 for l in leads if l.phone)
    no_web = sum(1 for l in leads if l.website_status == "No Website")
    social_only = sum(1 for l in leads if l.website_status == "Social Link Only")
    has_web = sum(1 for l in leads if l.website_status == "Has Own Website")
    unclaimed = sum(1 for l in leads if l.is_unclaimed_business)
    with_email = sum(1 for l in leads if l.emails)

    stats_table.add_row("Total Raw Scraped", str(result["total_raw"]))
    stats_table.add_row("Final Filtered Leads", str(total_leads))
    stats_table.add_row("Verified Phone Numbers", f"{has_phone} ({has_phone/total_leads*100:.1f}%)" if total_leads else "0")
    stats_table.add_row("No Website (Prime Leads)", f"{no_web} ({no_web/total_leads*100:.1f}%)" if total_leads else "0")
    stats_table.add_row("Social Link Only", f"{social_only} ({social_only/total_leads*100:.1f}%)" if total_leads else "0")
    stats_table.add_row("Has Own Website", f"{has_web} ({has_web/total_leads*100:.1f}%)" if total_leads else "0")
    stats_table.add_row("Unclaimed Businesses (Goldmine)", str(unclaimed))
    if with_email > 0:
        stats_table.add_row("Emails Extracted", str(with_email))

    console.print(stats_table)

    # Sample Leads Table
    if leads:
        sample_table = Table(title=f"🔍 Sample Extracted Leads (Top {min(5, len(leads))})", border_style="magenta")
        sample_table.add_column("Name", style="bold white")
        sample_table.add_column("Category", style="dim")
        sample_table.add_column("Phone", style="cyan")
        sample_table.add_column("Status", style="yellow")
        sample_table.add_column("Rating", style="green")

        for lead in leads[:5]:
            rating_str = f"{lead.rating}★" if lead.rating else "N/A"
            sample_table.add_row(
                lead.name,
                lead.category or "N/A",
                lead.phone or "None",
                lead.website_status,
                rating_str,
            )
        console.print(sample_table)

    export_panel = f"""[bold green]📁 Export Complete![/bold green]
[bold]JSON File:[/bold] {result['json_path']}
[bold]CSV  File:[/bold] {result['csv_path']}
[dim]Tip: You can directly open the CSV in Excel or upload it to Google Sheets / CRM.[/dim]"""
    console.print(Panel(export_panel, border_style="green", expand=False))


def main():
    parser = argparse.ArgumentParser(description="Autonomous AI Google Maps Lead Generation Agent")
    parser.add_argument("--prompt", "-p", type=str, help="Natural language lead generation request")
    parser.add_argument("--provider", type=str, choices=["gemini", "groq"], help="LLM Provider to use")
    parser.add_argument("--yes", "-y", action="store_true", help="Auto-confirm plan without interactive prompt")
    args = parser.parse_args()

    display_welcome_banner()

    user_prompt = args.prompt
    if not user_prompt:
        console.print("\n[bold]Describe what leads you need (in English or Bengali):[/bold]")
        console.print("[dim]Example: 'আমাকে ঢাকার রেস্টুরেন্টগুলোর লিড দাও যাদের ওয়েবসাইট নেই'[/dim]")
        user_prompt = Prompt.ask("\n[bold cyan]Your Request[/bold cyan]")

    if not user_prompt.strip():
        console.print("[red]Error: Request cannot be empty.[/red]")
        sys.exit(1)

    with console.status("[bold green]Analyzing request and planning geo-zones with AI...[/bold green]"):
        plan = generate_plan(user_prompt=user_prompt, provider=args.provider)

    # Display simple, clean human-friendly plan preview
    display_plan_summary_human(plan)

    # Human-in-the-Loop Confirmation
    if not args.yes:
        confirmed = Confirm.ask("\n[bold yellow]👉 Do you want to proceed with this search?[/bold yellow]", default=True)
        if not confirmed:
            console.print("[yellow]Search cancelled by user. You can try again with a revised prompt.[/yellow]")
            sys.exit(0)

    console.print("\n[bold green]🚀 Launching Lead Generation Pipeline...[/bold green]")
    result = run_pipeline(plan)

    display_results_summary(result)


if __name__ == "__main__":
    main()
