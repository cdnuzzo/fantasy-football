"""Entry point for the `ff` CLI -- registers each subcommand."""
import typer

from . import compare, roster, scoring_rules

app = typer.Typer(
    help="Fantasy football start/sit tools, backed by Sleeper and your ESPN league's own rules.",
    add_completion=False,
    no_args_is_help=True,
)

app.command(name="compare")(compare.command)
app.command(name="roster")(roster.command)
app.command(name="scoring-rules")(scoring_rules.command)


if __name__ == "__main__":
    app()
