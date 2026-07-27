from datetime import datetime


class CTime:
    def __init__(
        self,
        year,
        month,
        day,
        hour,
        minute,
        second=0,
        auto=True,
        tzinfo=None,
    ):
        self.year = year
        self.month = month
        self.day = day
        self.hour = hour
        self.minute = minute
        self.second = second
        self.auto = auto  # 自适应对天的理解
        self.tzinfo = tzinfo
        self.set_timestamp()  # set self.ts

    def __str__(self):
        if self.hour == 0 and self.minute == 0:
            return f"{self.year:04}/{self.month:02}/{self.day:02}"
        else:
            return f"{self.year:04}/{self.month:02}/{self.day:02} {self.hour:02}:{self.minute:02}"

    def to_str(self):
        if self.hour == 0 and self.minute == 0:
            return f"{self.year:04}/{self.month:02}/{self.day:02}"
        else:
            return f"{self.year:04}/{self.month:02}/{self.day:02} {self.hour:02}:{self.minute:02}"

    def toDateStr(self, splt=''):
        return f"{self.year:04}{splt}{self.month:02}{splt}{self.day:02}"

    def toDate(self):
        return CTime(
            self.year,
            self.month,
            self.day,
            0,
            0,
            auto=False,
            tzinfo=getattr(self, "tzinfo", None),
        )

    def set_timestamp(self):
        if self.hour == 0 and self.minute == 0 and self.auto:
            date = datetime(
                self.year,
                self.month,
                self.day,
                23,
                59,
                self.second,
                tzinfo=getattr(self, "tzinfo", None),
            )
        else:
            date = datetime(
                self.year,
                self.month,
                self.day,
                self.hour,
                self.minute,
                self.second,
                tzinfo=getattr(self, "tzinfo", None),
            )
        self.ts = date.timestamp()

    def __gt__(self, t2):
        return self.ts > t2.ts

    def __ge__(self, t2):
        return self.ts >= t2.ts
